# Secure options data recovery: obtain evidence, not another blocker label

Policy **2026-10-24-options-data-access-1**. This adds a bounded read-only adapter to the existing cross-check, contract, modeling and independent-review workflow. It does not change price alerts, create a research daemon, install a broker, subscribe to data, certify executable prices, or send orders.

## Recommended access ladder

| Route | Useful capability | What must be true | Actual integration status |
|---|---|---|---|
| Tradier production market-data REST | Consolidated live US equity/option bid/ask, sizes and separate bid/ask event times | Eligible Tradier brokerage account, supported secure token delivery, current entitlement | Read-only capture adapter implemented and fixture-tested; no credentials present in this runtime |
| Alpaca subscribed OPRA + SIP stock quotes | Second independently retrieved consolidated option route, synchronized stock bid/ask | Confirm OPRA and stock SIP entitlements separately; preserve quote-event timestamps | Read-only capture adapter implemented and fixture-tested; no credentials present |
| Alpaca free indicative | Research arithmetic and API-shape testing | Explicit indicative label; quotes are modified derivatives, not executable OPRA BBO | Supported as research data, fails actionable-quote data checks |
| IBKR existing entitled account | Broker contract reference, live snapshot-style market data | Actual subscriptions; identify live/frozen/delayed modes; API timestamps/contract IDs | Reviewed alternative, not installed or authenticated |
| Databento OPRA | Timestamped event history, definitions and replay; potential live/archive corroboration | Actual licensing, live/reference costs and symbology; same underlying OPRA lineage | Reviewed alternative, not installed; no free-live claim |
| Public Yahoo/Cboe wrappers | Historical/indicative exploratory data | Provider permits access, timestamps/terms preserved | Not a recovery route for fresh executable BBO; no new scraper |

Fresh official documentation was checked on **2026-10-24**. Fees and account eligibility change; verify in the provider's own subscription screen before any paid activation. We do not imply a particular user can open a brokerage account or meets market-data professional/nonprofessional classifications. A free MCP is not a free entitlement.

For this manual research task no installed Tradier, Alpaca, IBKR or Databento tool was observed in the runtime inventory, and expected credential environment variables were absent. A catalog search returning no match does not prove the provider is globally unavailable. Missing credentials are an exact external dependency; they do not prevent contract research, scenario arithmetic or test execution.

## Concrete secure setup

1. Use an existing entitled account when available; otherwise compare eligibility and actual subscription costs before choosing. Do not create accounts or activate paid data implicitly.
2. Prefer supported OAuth/secure application connection or a secret manager injecting process environment. Never paste a key in chat, a report, git, a prompt, a command-line flag or a plain saved config. The local adapter reads only `TRADIER_ACCESS_TOKEN`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`; it never prints them.
3. These credentials may authorize trading elsewhere. **The adapter's narrow endpoint/method allowlist does not make the original credential read-only.** Prefer a provider-supported data-only credential where available; otherwise isolate the credential behind a market-data-only proxy/process, restrict network egress, and keep broker account/order methods out of the agent tool inventory.
4. If choosing the official Alpaca MCP, pin/review an exact release/commit, then use `ALPACA_TOOLSETS=options-data,stock-data,assets,corporate-actions`. Inspect actual tool discovery after launch. Do not assume names or readOnlyHint annotations enforce permissions; the default server enables all toolsets. Do not enable `account`, `trading`, `watchlists` or `locates` for this research. No MCP installation has been performed here.
5. Confirm entitlement with a small exact-symbol **data request**, not an account-balance or test-order call. Check response feed and current timestamps; preserve errors. 401/403 is an access problem, not transient market noise. Paper/sandbox access is not proof of live entitlement. Market closure produces historical/closed status, never a synthetic fresh quote.

## Small adapter and actual boundary

`references/niulai-workflow/scripts/options_quote_capture.py` uses Python's standard-library HTTPS/JSON stack and the existing strict OCC parser. The XNYS clock imports the calendar dependency pinned in `references/niulai-workflow/scripts/requirements.txt`; calendar failure fails quote-data admission. The system Python initially lacked this package; that recoverable dependency was repaired with the existing pin and an installation receipt was retained. Actual calendar checks then distinguish a closed market from unavailable calendar infrastructure; no weekday guess is used. No new SDK or service is needed for a small REST capture.

- GET requests only to three fixed HTTPS market-data paths; reject arbitrary base URLs, order paths, changed response origins and redirects (credentials never follow redirects).
- At most 20 exact compact OCC contracts, one underlying, two providers; root-to-underlying mismatch requires another reviewed adapter rather than guessing adjusted/class-share mappings.
- At most one transient retry, bounded timeout and 10 MB response, explicit symbol coverage; failure of one provider or stock request preserves independent successful results.
- Persist retrieved time separately from provider bid/ask event times. Tradier epoch units must be explicitly configured and verified; ambiguous Unix units are not guessed. Alpaca supplies a combined quote-event time: both sides reference that event, **not two independently known side-update times**. Original nanosecond string is preserved; Python comparison rounds/truncates to microsecond precision, which is adequate only for the declared seconds-level tolerance.
- Preserve missing prices/times/sizes, quote condition/raw response and greeks separately. For option quote-data admission accept only verified OPRA BBO-eligible condition codes (space, A, B, O, C); reject F/I/R/T/X/Y or unknown/missing conditions. Tradier REST may omit condition data: preserve its useful quote but require another state-aware route or an explicit independently reviewed provider semantics solution before treating it as eligible here. Missing conditions are never silently assumed regular. Last trade is never a bid/ask substitute. Unknown adjustment, deliverable, exercise and settlement fields remain unknown; a provider `contract_size=100` alone does not certify standard 100-share deliverability.
- Quote-data checks cover actual XNYS state, future/stale/missing/zero-depth/crossed quotes, feed semantics, within-quote and stock/option time skew. IEX stock quotes are an explicitly narrower market and do not clear consolidated SIP-like quote admission here.
- Per-side two-route comparisons retain signed differences, a predeclared absolute/relative tolerance and asynchronous/ineligible/unavailable states. Never average discrepancies. Shared consolidated option feeds corroborate transport and state consistency, not independent economic truth or fill probability.
- Response hashes bind original bytes, not credentials/request headers. Saved response trees redact any known environment secret if echoed; a hash may therefore refer to pre-redaction bytes. Output is `captured_data_only`, `partial` or `blocked`; **`actionable_trade_approved` is always false**. Quote timestamps and supplied entitlement references still require independent authenticity review.

Example nonsecret configuration (the entitlement strings are placeholders, not receipts):

```json
{
  "underlying": "CRWV",
  "contracts": ["CRWV270416C00055000", "CRWV270416C00065000", "CRWV270416C00070000"],
  "providers": [
    {"provider":"tradier","feed":"consolidated_realtime","epoch_unit":"milliseconds","entitlement_ref":"REPLACE_WITH_ACTUAL_DATED_ENTITLEMENT_REFERENCE"},
    {"provider":"alpaca","feed":"opra","stock_feed":"sip","entitlement_ref":"REPLACE_WITH_ACTUAL_DATED_ENTITLEMENT_REFERENCE"}
  ],
  "policy": {
    "max_quote_age_seconds":15,
    "max_side_skew_seconds":5,
    "max_stock_option_skew_seconds":5,
    "price_absolute_tolerance":"0.05",
    "price_relative_tolerance":"0.01"
  }
}
```

These tolerances are an example **policy assumption**, not empirically calibrated CRWV execution settings. Freeze suitable tolerances before observing disagreement; don't widen them to pass a quote. A quiet contract with an older genuine quote may be useful diagnostic evidence, while failing this fresh-quote admission. The adapter is not a high-frequency execution gateway.

Run after secure credential injection:

```bash
python -m pip install -r references/niulai-workflow/scripts/requirements.txt
python references/niulai-workflow/scripts/options_quote_capture.py --config /absolute/nonsecret-config.json --output /absolute/quote-capture.json
python -m unittest discover -s references/niulai-workflow/scripts -p 'test_options_quote_capture.py' -q
```

A complete data response does not mean live eligible quotes: inspect every record's checks and failed coverage. Closed-market capture must not be dated as an open-market trade or substituted into historical research without an explicit rebase. Raw/norm inputs must be linked to the existing payoff/evidence packet and independently reviewed; the capture output is not itself that packet or an options completion certificate.

## Actively resolve the other data gaps

**Contract terms:** use Alpaca's official read-only assets `get_option_contract`/`get_option_contracts` or REST contract endpoint with `show_deliverables=true`, **explicit April 2027 expiration filter**, and full pagination/coverage. The endpoint's default expiration upper bound is the upcoming weekend, so an unfiltered response would silently miss these contracts. Compare size, underlying, strike/right, style and deliverable components with OCC series and any adjustment memos plus the intended broker's confirmation. Preserve exact source/date. Absence of a found memo is not affirmative proof of no adjustment. This lookup is documented, not yet authenticated/executed here.

**Stock/dividends/carry:** use synchronized authorized stock quotes, issuer corporate-action/dividend declarations and broker/exchange references. A class-wide zero-dividend assumption or historical issuer statement alone does not establish no future special dividend through expiry. Test both supported dividend and carry bounds in QuantLib. A T-bill curve is a modeling reference, not necessarily the user's actual funding rate; a short stock financing rate is not interchangeable with risk-free rate.

**Quote state versus fill:** collect a small time-bounded candidate-only sample after entitlement, retaining event time, arrival time, spread and sizes. Compare package long-ask minus short-bid and modeled limits, include fees/slippage and adverse simultaneous quotes. Two visible leg quotes are not a guaranteed atomic multi-leg fill. Before trading, the user's broker must confirm package order permissions, fees, physical exercise/assignment, cash needed and planned pre-expiry close; this research adapter never sends that order.

**Historical validation:** use licensed timestamped quote history for genuine option replay. The official Alpaca API documents options history since February 2024; Databento offers event/archive schemas and reference definitions. Historical availability alone doesn't provide historical entitlement, corporate actions, synchronized underlying data or executable fills. Databento specifically documents differences between earlier historical subsets and packet-capture-era timestamps/schemas; don't treat historical `ts_recv` blindly as live receive time.

## Primary sources and maintained repos actually reviewed

- Tradier [market data](https://docs.tradier.com/docs/market-data), [quote fields](https://docs.tradier.com/market-data/get-quotes), [endpoints](https://docs.tradier.com/overview/endpoints): consolidated live brokerage feeds, sandbox delay, hourly Greeks, separate `bid_date`/`ask_date`, contract_size. Quote-time units must be validated on the selected response version.
- Alpaca [feed descriptions/history](https://docs.alpaca.markets/us/docs/historical-option-data), [quote stream schema](https://docs.alpaca.markets/us/docs/real-time-option-data), [latest option quotes](https://docs.alpaca.markets/us/v1.4.2/reference/optionlatestquotes): free indicative is modified; OPRA is subscribed; stream is MsgPack and quote-event timestamped.
- Official [Alpaca MCP](https://github.com/alpacahq/alpaca-mcp-server), [toolset docs](https://docs.alpaca.markets/us/docs/trading-api-mcp), [Python SDK](https://github.com/alpacahq/alpaca-py): reviewed, not installed; no claim that an unpinned third-party wrapper preserves timestamps or safe scope.
- Alpaca [contract lookup](https://docs.alpaca.markets/us/reference/get-options-contracts): show_deliverables, expiry bounds, style and pagination. [OCC series search](https://www.theocc.com/market-data/market-data-reports/series-and-trading-data/series-search): authoritative reference entry point, not yet contract-specific verification.
- IBKR [streaming market data](https://www.interactivebrokers.com/docs/tws-api/doc/md/streaming-data), [subscriptions](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/introduction): snapshot-style option updates and subscription requirements; not installed.
- Databento [official Python client](https://github.com/databento/databento-python), [OPRA dataset](https://databento.com/docs/datasets/opra-pillar), [quickstart](https://databento.com/docs/quickstart): maintained official client, OPRA timestamps/reference/replay; not installed or licensed here.

No provider's promotional claim proves alpha, data authenticity, gap-free coverage or a particular user's ability to trade. The improvement is an executable evidence-recovery route and tested conservative admission—not pretending the remaining external access dependency has vanished.

- OPRA [Binary Data Recipient Interface Specification v6.4b, 2026-08-25](https://cdn.opraplan.com/documents/OPRA_Pillar_Output_Specification.pdf), §6.04 and Appendix D: BBO-eligible quote types, nonfirm/indicative/rotation/halt states and zero-price rules. Provider condition mapping still requires verification; a live feed alone is not a firm quote.
