# Factor source inventory contract

This package records the selected-but-disabled routes and what must be verified before real factor data may enter the
point-in-time builder. It performs no downloads, logins, provider calls or data
queries and stores no values, authentication material, private identifiers or outcomes.

`candidate-real-inventory.json` freezes selected routes for DFII5,
BAMLC0A0CM, DFF, SPY and ONEQ. Every account/API-access/order/entitlement/license,
retention and PIT receipt remains `null` under an exact blocker roster. The record
is `selected_disabled_unverified`, invokes nothing and can never be marked
real-ready by this contract.

Selected routes:

- DFII5: FRED/ALFRED primary; Federal Reserve H.15 DDP fallback requiring contemporaneous capture.
- BAMLC0A0CM: FRED/ALFRED internal-research-only primary with no redistribution; directly licensed ICE Consolidated History fallback.
- DFF: FRED/ALFRED primary; New York Fed Markets Data API fallback requiring contemporaneous archive.
- SPY/ONEQ: Databento `EQUS.MINI` unadjusted bars plus versioned PIT corporate actions primary; Massive unadjusted bars/actions fallback; Tiger operational cross-check only and never PIT-admissible.

Market routes require provider-native listing identity, effective intervals and a
versioned mapping; ticker-only backfills are forbidden. Databento events use
`event_unique_id` and select the maximum `ts_record` available at the cutoff,
with corrections superseding prior versions and cancellation removing the event.
Executable bars remain unadjusted. Total return is reconstructed under frozen
`effective-date-next-close-reinvestment-v1` (the first unadjusted session close
on or after the effective date) and `pit-total-return-log-v1` policies. Massive requires a contemporaneous archive or contracted correction
feed plus commercial/cache-deletion receipts. Tiger is never research-admissible
without PIT action revisions and remains cross-check-only.

`handoff.py` maps value-free synthetic provider response commitments into the PIT
builder vocabulary. ALFRED `date`, `realtime_start` and `realtime_end` map to
observation/vintage timing while `value` is represented only by a commitment.
Databento `ts_created`, `ts_record`, effective dates, provider-native listing ID,
`event_unique_id`, correction and cancellation map to published/available/
observed/vintage/supersession identities. Tracked fixtures contain no values.

Official references used by the selection snapshot:

- <https://fred.stlouisfed.org/series/DFII5>
- <https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html>
- <https://fred.stlouisfed.org/docs/api/fred/series_observations.html>
- <https://fred.stlouisfed.org/series/BAMLC0A0CM>
- <https://alfred.stlouisfed.org/series?seid=BAMLC0A0CM>
- <https://www.ice.com/fixed-income-data-services/access-and-delivery/connectivity-and-feeds/ice-consolidated-history>
- <https://www.ice.com/fixed-income-data-services/data-and-analytics/disclaimer>
- <https://fred.stlouisfed.org/series/DFF>
- <https://markets.newyorkfed.org/static/docs/markets-api.html>
- <https://databento.com/catalog/us-equities/EQUS.MINI/etf/SPY>
- <https://databento.com/catalog/us-equities/EQUS.MINI/etf/ONEQ>
- <https://databento.com/docs/api-reference-reference/corporate-actions/corporate-actions-get-range>
- <https://databento.com/pricing>
- <https://massive.com/docs/rest/stocks/aggregates/custom-bars>
- <https://massive.com/legal/market-data-terms-of-service>
- <https://docs-en.itigerup.com/docs/quote-stock>
- <https://docs-en.itigerup.com/docs/corp-action-cpp>

The synthetic fixture exists only to test the positive structural path. Its
receipts and policies are explicitly synthetic and do not validate the candidate
providers.

Semantic inventory identity excludes `inventory_alias`, path, inventory name and
row order, so renaming or repackaging cannot create fresh evidence. Provider,
product, series, role, unit, revision and attestation semantics remain identity
bearing.

Run from the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s factor/source_inventory/tests -v
```

Allowed claim: required source metadata and attestation requests are strict,
deterministic and fail closed while real facts are unresolved.

Not established: provider ownership, license or retention rights, point-in-time
availability/receipts, vintage completeness, calendar/security-master attestations,
policy/missingness receipts, data quality, market values, labels,
protected evidence, baseline reproduction, alpha, EV, Kelly or run authority.
