# Lightweight source and calculation cross-checks

Policy **2026-10-24-crosscheck-1**. Apply to new research and material revisions across companies, funds, crypto and derivatives. Reuse one normalized snapshot, the existing source archive, model dependencies and independent review. This adds no sender, scraper, database or trading permission.

## Spend verification effort where it can change the decision

Cross-check decision-critical identity, price, share/debt/cash amounts, material operating drivers, contract terms, forecast horizons and payoff outputs. Verify unusual or decision-flipping numbers first. Reuse dated verified values until their relevant event/validity boundary; do not fetch the same annual filing twice per ticker stage. Cache with exact source/record identity, revision, reporting period, availability and payload hash. A cache lifetime is a recorded policy, not evidence that an unrefreshed market quote is current.

Use an original authoritative source plus an independently obtained comparison where possible. For accounting, reconcile filing statements/notes and issuer materials on the same period and definition; two copies of the same filing corroborate extraction, not the economic claim independently. For live options use two entitled quote routes, matching exact OCC contract/deliverable, bid/ask side, event time, session and feed. Two vendors distributing OPRA corroborate routing/transcription and synchronization, not two independent markets. Missing upstream lineage stays unknown. Do not call two Yahoo wrappers independent.

Normalize identity, currency, units, scale, period, fiscal/calendar definition, adjustment basis, event versus availability time, raw/adjusted price, close/last/bid/ask and realtime/delayed/indicative status **before comparing values**. A quote response timestamp, last-trade time and current bid/ask time are distinct. A share count may be basic, diluted, weighted average, period-end or fully diluted; do not average their disagreement. Field semantics must be read from provider documentation.

## Small deterministic comparison

Run `references/niulai-workflow/scripts/evidence_crosscheck.py --input PACKET.json --output RESULT.json` on two normalized critical observations. Use the adjacent test's `example_packet()` as the interface. Declare absolute/relative tolerance and permitted age/skew before seeing the discrepancy. Use reporting precision, tick size, metric volatility and the decision's sensitivity to justify them; never widen a tolerance after a failure merely to pass. Retain both raw values and the signed/absolute difference. Never silently average.

The helper distinguishes agreement, shared-upstream corroboration, disagreement, incompatible definitions, stale/missing/unverifiable data. Its result establishes consistency of supplied metadata and numbers, not source authenticity or source independence in fact. A contract string supplied by the caller is not an OCC verification. When metadata are incomplete, keep the observation and report the precise missing field instead of treating null as zero.

Provider HTTP200, MCP `isError:false`, a nonempty message or a worker finishing are not coverage proof. Inspect semantic error messages, expected symbol/contract coverage, field types, timestamps and actual payload contents. In this review Tradier returned a missing-key error inside a nominally successful transport result. Do not retry an authentication error as if it were transient market data.

## Independent calculation checks

Do not rerun the same function twice and call that independent verification. Use an algebraic identity, different algorithm/implementation, hand-derived small example or separately written oracle. Examples: balance-sheet and cash reconciliation; DCF equity bridge; exact expiration payoff versus case enumeration; put-call parity and finite-difference Greeks; Decimal customer economics versus Fraction oracle. Test boundaries, signs, units, timestamps, missingness and invariants as well as a normal case. Reuse existing test suites; do not write a second entire pricing library merely for verification.

Recomputation and independent checks are different: the first ensures saved outputs match pinned inputs/code, the second can expose a shared formula error. Neither proves the forecast assumptions. Monte Carlo outputs require seed, convergence and analytical/limiting benchmarks; identical seeds are reproducibility, not independent evidence.

## Handle conflicts without abandoning unrelated work

Keep a small discrepancy record: key, both source IDs/hashes, values/definitions/times, tolerance, status, likely explanation, chosen authoritative value or unresolved range, affected model lines and next check. A documented correction creates a new version; retain the original. If the discrepancy can change the action, recompute both bounds or block only the affected actionable conclusion. If immaterial, preserve the warning and explain why it does not change the result.

One unavailable source does not erase the other source or stop all independent work. Use an explicitly labeled single-source research calculation when useful. Do not issue a fresh executable option-price recommendation without verified contract/quote data. Do not treat partial coverage as zero hits or relax a quote gate to meet a deadline. Normal price summaries keep their existing source/resilience policy and disclose gaps; this research extension does not silently modify production alert thresholds, cadence or provider behavior.

Attach comparison input/output hashes and the independent calculation review to the existing research run. A material options trade review additionally uses the options policy. The reviewer verifies critical-input coverage and economic consequences; this small helper does not intercept every possible tool call or enforce source truth globally.

## Source foundations

- [Tradier market-data documentation](https://docs.tradier.com/docs/market-data): quote entitlement, delayed versus realtime feeds and separate hourly Greek refresh.
- [Alpaca option-data documentation](https://docs.alpaca.markets/us/docs/historical-option-data): indicative derivatives are not OPRA BBO. Do not compare them as interchangeable executable quotes.
- [Philadelphia Fed real-time data documentation](https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists): observation vintages and revised history.
- [OCC equity specifications](https://www.theocc.com/clearance-and-settlement/clearing/equity-options-product-specifications): standard contract conventions; adjustments still require contract-specific verification.

The risk-tiered caching, conflict log and tolerance workflow are our engineering design, not an empirically demonstrated investment-alpha result from these sources.

## Enforced critical-input ledger — 2026-10-24

New full company/fund/crypto records are checked by `critical_data_evidence.py` from both finalization and completion. The effective timestamp is `2026-10-24T00:10:31Z`; actual new publication timestamps also activate the check, so an old subject cutoff does not exempt a new publication. Earlier published records are preserved without retroactive certification.

Bind the complete model-artifact inventory and each declared decision-critical input to actual JSON pointers and values. Recompute the existing comparison packet and bind saved source hashes, definitions, units and dates. When a second comparable source genuinely does not exist, retain the primary passage, alternative retrieval attempt, reason, numerical lower/base/upper sensitivity, resulting actions and independent review. An exception that changes the action permits wait/no_buy, not an unsupported buy. This is a risk-based verification policy, not a requirement to fetch every number twice.

The independent reviewer must reconcile the inventory against the full model and inspect source extraction, omitted material inputs and sensitivity arithmetic. The validator rejects missing declared coverage, stale artifacts and unsupported exceptions; it cannot discover all undeclared economic assumptions or authenticate a source merely from a hash. Use `test_critical_data_evidence.py` for the current packet interface. Existing options-specific quote and contract requirements continue separately.
