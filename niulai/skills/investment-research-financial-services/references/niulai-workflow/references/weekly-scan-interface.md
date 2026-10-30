# Weekly research review scanner

This module ranks an explicitly supplied research universe by the last completed US trading week's **total return**. Price moves select the names requiring review. They do not establish whether a thesis improved and never change an EV, alert, or portfolio position by themselves.

## Files and dependencies

- `weekly_scan.py`: Python module and offline CLI. Python standard library except for `exchange_calendars==4.11.2` used for XNYS dates and close times.
- `test_weekly_scan.py`: 18 offline tests covering sessions, boundaries, invalid observations, adjustments, ties, configurable selection and invalid fractions.
- This directory contains no quote API client or credentials. Neither importing the module nor calling `rank_week` writes files or makes network requests.

## Module API

```python
from weekly_scan import completed_week, rank_week
boundaries = completed_week("2026-10-18T04:08:05+08:00")
result = rank_week(universe, observations, "2026-10-18T04:08:05+08:00")
result = rank_week(universe, observations, "2026-10-18T04:08:05+08:00", tail_fraction="0.10")
```

An optional `week_start="YYYY-MM-DD"` requests a historical Monday. An unfinished or future requested week raises `ValidationError`; an omitted week automatically selects the latest week whose final scheduled XNYS session has closed. The actual close time handles DST and 13:00 early closes. A Thursday before a Friday market holiday can complete a week. The starting price is the previous week's final session close; the ending price is this week's final session close.

`universe` is a list of objects, or in the CLI the existing research catalogue containing a `securities` list:

```json
[
  {"id":"security:MU","symbol":"MU","security_type":"equity","name":"Micron"},
  {"id":"security:SOXL","symbol":"SOXL","security_type":"leveraged_etf","leverage_label":"3x daily reset"}
]
```

Universe symbols and identifiers must each be unique. Symbols are explicit uppercase values, with no silent alias replacement. Fund type and supplied leverage labels are retained. Fund returns are ranked with the configured universe; they are not divided by leverage. Other historical research fields do not influence the ranking.

`observations` is a flat list of timestamped daily adjusted-close records. Only the two required endpoint sessions are used. A provider batch should fetch both endpoints together under one adjustment snapshot:

```json
[
  {
    "symbol":"MU",
    "session":"2026-10-09",
    "adjusted_close":"100.12",
    "currency":"USD",
    "price_unit":"currency_per_share",
    "adjustment_basis":"split_and_dividend_adjusted_total_return",
    "adjustment_snapshot":"provider:retrieval-batch-20261017-001",
    "source":"provider name + endpoint",
    "observed_at":"2026-10-17T00:00:00Z"
  },
  {
    "symbol":"MU",
    "session":"2026-10-16",
    "adjusted_close":"110.34",
    "currency":"USD",
    "price_unit":"currency_per_share",
    "adjustment_basis":"split_and_dividend_adjusted_total_return",
    "adjustment_snapshot":"provider:retrieval-batch-20261017-001",
    "source":"provider name + endpoint",
    "observed_at":"2026-10-17T00:00:00Z"
  }
]
```

`observed_at` is the final price's retrieval/observation timestamp, not the start-of-day timestamp attached to a vendor's daily bar. It must be at or after the relevant scheduled close, and no later than the requested `as_of` cutoff. Prices are provider decimal text, not binary float values. Both endpoints must use the same currency, unit, provider, adjustment basis and adjustment snapshot. A fresh raw close is not a substitute for a missing adjusted historical close. The engine validates the metadata contract; it cannot independently prove a provider's adjustment method, which remains an adapter/source responsibility.

## Selection and output

For `N` valid securities and the configured `tail_fraction`, each tail contains `min(ceil(N * tail_fraction), floor(N / 2))`. The default is `"0.20"`; with all 37 current names covered, this is **8 top + 8 bottom**. At `"0.10"`, it selects **4 top + 4 bottom**. The fraction must be finite decimal text or a Decimal, greater than zero and at most 0.5; booleans and binary floats are rejected. Missing or invalid endpoint coverage reduces `N`; the result reports the exclusions and resulting counts. It never assumes zero for missing data. No valid names means no selected names, not a successful full-universe scan. Output `method.selection_fraction` records the exact normalized decimal fraction used.

One full ordering sorts total return descending, then symbol ascending. The first `k` entries form the top group and last `k` the bottom group. This resolves exact boundary ties deterministically and prevents overlap, even if every return is equal. The bottom group is displayed with worst return first and symbol ascending. Return is calculated with Decimal precision 40 and serialized as decimal text.

The result includes:

- `boundaries`: requested cutoff, actual sessions and UTC closing timestamps.
- `coverage`: total, valid, excluded, selected count per tail, completeness and per-security reasons.
- `ranking`, `top_performing`, `bottom_performing`: total returns, endpoint adjusted prices, timestamps, source and adjustment snapshot.
- `input_provenance`: hashes of explicit universe and endpoint observations, calendar package/version.
- `price_move_is_thesis_evidence: false`: downstream research must find evidence independently.

Duplicate/ambiguous identifiers or endpoint records, malformed timestamps, and future/unfinished explicitly requested weeks raise `ValidationError`. Invalid individual endpoint values, mismatched units, preclose/future observation times, raw closes, or missing points exclude that security and record the reason. Unknown observation symbols are disclosed in `ignored_symbols` and never enlarge the explicit universe.

## CLI

```bash
python weekly_scan.py --universe /root/niulai/runtime/research.json --observations adjusted_observations.json --as-of 2026-10-18T04:08:05+08:00 --tail-fraction 0.20 --output weekly_scan.json
python -m unittest -v test_weekly_scan
```

Only an explicit `--output` writes a file. No database, schedule, alert or live site is changed by this CLI.
