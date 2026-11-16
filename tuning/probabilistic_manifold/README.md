# Probabilistic manifold support slice

This directory owns one exploratory, read-only capability: construct a point-in-time
feature panel for TQQQ and simple comparators, then describe whether the latest row
resembles the historical **training cloud**. Despite the directory name, this emits
no probability, forecast, expected return, confidence, position size, or action.
The only status vocabulary is `inside`, `edge`, `outside`, or `inconclusive`.

## Reproducible run

From the workspace root:

```bash
.research-sources/.venv/bin/python -B -m tuning.probabilistic_manifold.cli \
  --source-root "$PWD" \
  --output-root "$PWD/tuning/probabilistic_manifold/artifacts"
.research-sources/.venv/bin/python -B -m unittest discover \
  -s tuning/probabilistic_manifold/tests -p 'test_*.py' -v
```

Source and output roots are explicit local trust boundaries. The root and every
existing ancestor must be non-symlink directories owned by the current UID or root,
not group/world writable; descendants must stay on the root device. Every configured
source and output name must be a normalized relative POSIX path: absolute paths and
dot segments are rejected. Source path/SHA-256/bytes/symbol/date range are verified
before parsing. A held root descriptor detects root-object drift, while path
components are revalidated immediately before use. Same-UID concurrent ancestor
replacement remains outside this local threat model; this is not tamper resistance
against another process running as the same user.

Canonical JSON publication uses a unique same-directory `O_CREAT|O_EXCL|O_NOFOLLOW`
mode-0600 temporary file, write-all, file `fsync`, `os.replace`, parent-directory
`fsync`, stable no-follow readback, and cleanup. The two files are not one atomic
transaction: publication writes the payload manifest first and the authority packet
second. Consumers must accept a pair only when `packet.source_manifest_sha256`
exactly matches the manifest bytes. A failed packet publication leaves no accepted
new pair; recovery is hash reconciliation, not an additional control plane.

## Two separate statuses

`status` is the current integration status, while `support_geometry.status` is
nested and strictly descriptive of the historical training cloud. The frozen SOXL
snapshot has one historical origin, `origin_2026-11-05`. Its query distance is
between the target-derived SOXL q95 and q99 distances, so the raw geometric class is
`edge`; the published geometry and top-level statuses are nevertheless
`inconclusive` because dependence-adjusted ESS is
`2.3968295904887715`, below the frozen minimum `2.5`, and
`probability_feature_compatible=false`. The shared support-v1 design constants are
not independently validated for SOXL, while the fitted SOXL q95/q99 distances are
target-derived and are not transported from TQQQ. The closed
`leveraged-price-path-support-v1` method contract freezes all formula windows and
constants plus the exact `core.py` and `soxl_support.py` hashes. It is a shared
generic design specification, not evidence of SOXL/TQQQ predictive parity or SOXL
validation. Descriptive geometry cannot override this abstention and is not outcome
support.

The reported q95/q99 values are named **in-sample empirical training-cloud
quantiles**. They are not out-of-sample thresholds, predictive hurdles, or calibrated
probabilities. Pairwise training-feature correlations, 126-session nonoverlap count,
and overlap-kernel effective sample size keep collinearity and thin dependence-adjusted
evidence visible.

## Point-in-time boundary and outcomes

The support computation module imports only `core.py` among project modules; the CLI imports that module plus the atomic writer from `core.py`. Neither imports or calculates future outcomes. `outcomes.py` and closed `outcomes-config.v1.json` separately implement mature-only 126/252-session return,
path max drawdown, relative-QQQ return, and material-loss labels for isolated tests or
future explicitly governed evaluation. Training-cloud eligibility is based only on
chronology and horizon distance from the origin, not on reading label values.

Features use only observations on or before each row: TQQQ/QQQ 21/63/126-session
returns, 126-session distance from high, 21-session annualized realized volatility,
63-session downside semivariance, a simple 21-session TQQQ-versus-compounded-3x-QQQ
gap, and optional 21-session SPY/TLT/HYG diagnostics. Optional proxies are excluded
from kNN because available local histories begin only in 2025.

## Basis and claim limits

The source field is current-vintage adjusted exchange-traded **market price**. It is
not sponsor NAV, an intraday reset value, or an exact daily-reset benchmark.
Corporate-action adjustments can restate historical prices; this slice does not
reconstruct the adjusted-price vintage available on each historical date. The
126/252-session horizons are descriptive holding-period approximations and do not
reconstruct sponsor NAV or leverage-reset mechanics.

This slice provides no evidence of factor predictiveness, generalization, causal
effect, net alpha, or live suitability. It performs no standalone predictive hurdle,
protected threshold search, or protected-outcome read. Those claims require a
separately preregistered untouched/prospective evaluation with costs, vintage-aware
data, and dependence controls.

## Rolling-origin preregistration

`rolling-config.v1.json` and `rolling_origin.py` define a development-only,
metadata-first rolling-origin protocol. The CLI only regenerates the session,
development-split, preregistration, protected-split, and empty hash-chained ledger
receipts; it has no real-outcome run command.

The protocol is bound to the frozen v2 source manifest, an observed XNYS session
roster, current-vintage Yahoo adjusted market prices, and the 2010-08-12 origin
anchor. Development labels may be loaded lazily only for allowlisted origins whose
outcomes mature by 2023-12-29. A 21-session embargo follows that cutoff; protected
origins begin 2024-02-01 and remain unmaterialized and unopened.

The primary decision is 126-session material-loss Brier score versus the
training-only unconditional prevalence baseline. The 126-session return
distribution and tail metrics are secondary descriptive results. Max drawdown,
relative QQQ, all 252-session results, 21-session diagnostics, and the optional
macro-family ablation are exploratory and non-selective. Selection from monthly
diagnostics is prohibited. Tail thresholds use every training-eligible origin
before support abstention; candidates and baselines are scored on identical
retained origin IDs. All-abstain cases report abstention 1.0 with null metrics and
an inconclusive status.

The paired nonoverlap-origin bootstrap is frozen at 1,000 repetitions and seed
1262024. Adoption requires negative candidate-minus-baseline Brier delta and a
95% upper bound below zero; a positive lower bound rejects, numerical zero ties,
and all other cases remain inconclusive. Only the single primary comparison can
select; no multiplicity adjustment is claimed for descriptive/exploratory output.

The canonical attempt ledger binds config, preregistration, source, calendar,
code, evaluator, development split, candidate and target identities. It permits
only registered-to-completed/failed transitions, preserves failures, limits the
lifetime budget to the two frozen variants, and forbids protected-outcome access.
None of these development structures demonstrates predictive value, alpha, or a
trading action.

### Linked v2 execution authority

`rolling-config.v2.json` and the changed-hash `rolling_origin.py` supersede the
blocked execution authority while preserving v1 receipts as history. The primary
candidate is fixed to `price_path_base`; primary origins require 18 purged and
embargoed training origins, and fewer than five retained evaluations force an
inconclusive decision. Secondary-252 remains preregistered exploratory and is not
executed by the first development runner.

`V2DevelopmentDataAdapter.from_receipts` derives its allowlist from hash-verified
config, preregistration, development split, source manifest, calendar roster,
runner, outcomes and evaluator identities. It has no protected path/ID input and
loads labels lazily only for allowlisted development IDs. `rolling_outcomes.py`
contains the exact -25%/126 and -40%/252 formulas; the historical -30% outcomes
config is explicitly retired from v2.

The development-only runner registers its attempt before lazy label access, uses
expanding primary chronology, permits only the primary base candidate to select,
requires matched retained origins for candidate/baseline scoring, and reports
exact evaluated/retained counts. Secondary, monthly diagnostics and macro
ablation cannot select. No real development run is performed by preregistration.

The v2 ledger is authority-bound and hash-chained. `fcntl` locking plus expected-
head compare-and-swap rejects stale heads, rollback, reset and budget replay.
Failed attempts consume the lifetime two-variant budget. Result and ledger writes
use digest reconciliation; an unresolved write becomes `UNKNOWN_WRITE` and must
be reconciled before retry.
