# Calculation candidate and independent validation

The frozen copy below remains intact. A separate quality phase now lives in
`validation/`, with isolated corrections in `operators/`. Neither is wired into
production. See the [validation runbook](../../docs/deployment/calculation.md)
for public-input lineage, offline boundaries, dependency pins, numerical scope
and scheduled acceptance. A passing bounded test is not universal certification.

Status: copied, isolated from active workflows; not numerically certified or
accepted for scheduled production. User scope on 2026-10-31 is to preserve the
existing calculators first and decide changes/CRUD later. No active imports,
scheduler allocations, model configuration or original Niulai files are changed.

`manifest.json` records the original workspace path, exact SHA-256/size, copied
path, definitions, capability, dependencies and limitations of each file. Copies
retain their original bytes, formulas, validation, errors, imports and CLI entry
points. No private state, historical account fixtures or credentials are copied.
The upstream DCF validator's license is retained alongside it.

| Area | Copied implementation | Boundary retained |
| --- | --- | --- |
| DCF / enterprise value | `legacy/valuation/valuation_core.py` | PV, gross-debt WACC, terminal FCFF, enterprise-to-equity/per-share bridge |
| Expected value / case comparison | `legacy/workflow/entry_policy_ev.py`, `options_decision_bounds.py` | Supplied paths/weights/bounds; probabilities not calibrated by the calculator |
| Compounding / path summaries | `legacy/valuation/leveraged_funds.py` | Reset leverage, drawdown, weighted quantiles/tails, moving-block resampling |
| European options | `legacy/workflow/options_scenario_checks.py` | BSM, Greeks, IV inversion and conditional scenarios; European assumptions |
| Volatility surface | `legacy/workflow/options_surface_checks.py` | Total-variance interpolation on common support; sampled checks do not certify arbitrage freedom |
| American options | `legacy/workflow/options_american_checks.py` | Optional QuantLib 1.44 adapter; flat-vol FD diagnostics and grid convergence |
| Conditional probability paths | `legacy/workflow/options_path_checks.py` | GBM/bootstrap paths and expiry P&L; Monte Carlo intervals exclude model uncertainty |
| Payoffs / budget / costs | `legacy/workflow/options_payoff_checks.py` | Inherited supported long-call/spread and contract/fee conventions |
| Financial periods / vintages | `legacy/workflow/cycle_checks.py`, `cycle_vintage_checks.py` | Explicit financial arithmetic and point-in-time case consistency |
| Holdings / P&L / return | `legacy/holdings/` | Existing aggregation, quantity reconciliation, session and return conventions |
| DCF spreadsheet validator | `legacy/validation/validate_dcf.py` | Checks cached values/formula strings; does not recalculate Excel |

There is no discovered general calibrated real-world probability-surface engine
or general historical executable-fill replay engine in this copy. Supplied-case
replay, conditional simulated paths and risk-neutral valuation remain distinct.
Email MIME replay and provider quote acquisition are outside this calculation copy.

## Inspect and verify

From the workspace root, using Python >=3.9 and the standard library:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m shared.calculation list
PYTHONDONTWRITEBYTECODE=1 python3 -B -m shared.calculation verify
```

Verification checks all 34 source/copy byte pairs and Python syntax. It does not
execute the legacy calculators or prove their formulas correct. Selected inherited
synthetic tests are retained, unchanged, beside their respective modules. The
path-dependent original entry-policy test is retained under `legacy/original_tests/`
as a reference and is not included in the smoke commands below.

```sh
mkdir -p .job-runtime/calculation/tmp
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.job-runtime/calculation/tmp" \
PYTHONPATH="$PWD/shared/calculation/legacy/valuation" \
  python3 -B -m unittest test_valuation_core test_leveraged_funds
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.job-runtime/calculation/tmp" \
PYTHONPATH="$PWD/shared/calculation/legacy/workflow" \
  python3 -B -m unittest test_options_payoff_checks test_options_scenario_checks \
  test_options_surface_checks test_options_decision_bounds \
  test_cycle_checks test_cycle_vintage_checks
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.job-runtime/calculation/tmp" \
PYTHONPATH="$PWD/shared/calculation/legacy/holdings" \
  python3 -B -m unittest test_analytics
```

The module search path is explicitly local to each command because the inherited
scripts use sibling absolute imports. Do not add it to shell profiles or global
Codex settings. A normalized public operator API is deferred. For example, the
independent valuation module is already importable without optional packages:

```python
from shared.calculation.legacy.valuation.valuation_core import equity_value
```

No dependency installation is required for catalog/parity or the listed tests.
American and stochastic-path calculators retain optional dependencies. Their
inherited requirements under `requirements/` are reference snapshots, not a new
approved environment or fully resolved lock. In particular the DCF requirements
are ranges. Do not globally install these packages or claim those paths tested
by running the stdlib subset.

## Later decisions, deliberately deferred

Keep future operators below scripts/models: typed inputs and explicit units,
currency, dates, source basis, numeric policy, result/error contract and version.
Separate deterministic computation from source fetching, assumption calibration,
reporting, storage and scheduling. Preserve these snapshots as comparison evidence
when introducing a reviewed operator API; do not silently rewrite them.

Financial correctness, floating-point stability, model assumptions and predictive
calibration need separate acceptance. Proposed validation tools and deployment
boundaries are in [the runbook](../../docs/deployment/calculation.md). Broad new
stress suites and numerical fixes were outside the historical copy-first stage;
the subsequent validation phase adds them separately. API/CRUD, persistence and
production migration remain deferred. Before runtime integration apply the
[scheduled Codex acceptance contract](../../docs/deployment/runtime-acceptance.md)
and email the actual result; copying and shell tests are not scheduled acceptance.
