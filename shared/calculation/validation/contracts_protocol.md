# Spreadsheet screening and inherited P&L protocol v1

Frozen on 2026-10-31 before baseline/candidate execution. Legacy sources stay
unchanged. Only a separate OOXML screening helper is introduced. Public factual
input testing is covered by the valuation/options/paths suites; this ingress and
numeric contract suite uses synthetic inputs only and makes no live-data claim.

## Spreadsheet scope and criteria

The helper screens .xlsx ZIP/XML bytes offline; it never evaluates Excel,
starts an external application, follows links or accesses the network. Passing
screening is not DCF/model numerical acceptance. Explicit bindings identify the
literal annual-decimal WACC and terminal-growth cells; require finite numeric
literals, WACC>-1, growth>-1 and growth<WACC for this stated Gordon-domain check.
No 5%-20% heuristic is used as a mathematical validity criterion.

Frozen resource bounds: compressed input <=2MiB; <=128 ZIP members; each member
<=2MiB uncompressed, total <=8MiB; expansion ratio <=100; no encryption or
unsupported compression. Require contained nonsymlink regular input files under
the explicitly supplied allowed_root (default calculation runtime). Reject
duplicate/traversal ZIP paths, malformed XML and XML DTD/entity constructs.

Candidate must reject Excel error cells, nonfinite numeric/cache values, external
relationships/links/connections, macros and external/unsafe formula constructs.
Formula cells without numeric cached results return `unverified`; even cached
formulas only pass structural screening, not independent recalculation. Missing
or formula-based bindings also remain `unverified`, never numerically approved.

Predeclared synthetic cases: valid literals; uncached `=1/0`; an explicitly
cached Excel error; unsafe WEBSERVICE/external-workbook formula; external
relationship; formula binding; missing binding; growth>=WACC; nonfinite binding;
duplicate/traversal/encrypted/oversized ZIP indicators; DTD; input file outside
the permitted boundary. Baseline read-only check demonstrates whether the copied
validator produces PASS/errors0 for an uncached formula and reports the
Workbook.get warning. Record that baseline result as a failure of the broad
validation claim even if corrected screening handles the same input safely.

## P&L coverage and interpretation

Run copied `legacy/holdings/test_execution_pnl_independent.py` unchanged in the
project-local validation environment with pandas2.2.3/calendar4.11.2. Label
results INHERITED coverage, not a newly independent oracle or holdout. Capture
counts, failures, skips and dependency versions; do not bypass date errors.

Add at most four separately specified stock cases with exact Fraction oracles:
no trade, intraday buy, intraday sell and roundtrip, at adjacent XNYS closes.
Compare gross/net Decimal values exactly for finite decimal rational cases;
quantity and ledger identity must reconcile. A fill at the opening boundary is
excluded/rejected, a fill at the closing boundary is included, and a fill after
close is rejected. Corporate actions, tax, financing and option P&L are outside
this stock-contribution calculation. These checks do not certify total account
P&L or executable historical fills.

Record target baseline and candidate screening verdict separately in
run(output_dir,sample_path=None), retain every failure and skipped path, and keep
generated files under .job-runtime/calculation/validation/contracts/. Root owns
offline isolation, aggregate source fingerprints, scheduled Codex execution and
verified result-email synchronization. No production or scheduled acceptance is
established by this local suite alone.
