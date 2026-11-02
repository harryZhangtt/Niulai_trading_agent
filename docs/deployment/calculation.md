# Calculation copy and future validation

The [calculation candidate](../../shared/calculation/README.md) contains exact
copies of existing workspace calculators and selected synthetic tests. This
2026-10-31 stage has no active workflow integration, new environment, scheduler
allocation, global settings or installed package changes. It is not a claim of
institutional numerical certification. CRUD and public operator API design are
deferred by the user. Original Niulai source and private archives are preserved.

Source: `shared/calculation/`; provenance/capabilities: `manifest.json`; private
receipts/temp files: `.job-runtime/calculation/`. Setup requires only Python >=3.9
for the standard-library catalog verifier and selected inherited tests. Follow
the exact commands and optional-dependency boundaries in the component README.
No operational dependency on globally installed skills or packages is added.

Copy-stage verification: all 34 source/copy byte pairs matched and 227 selected
inherited synthetic tests passed (44 valuation/path-summary, 169 workflow and
14 holdings analytics). No new independent stress/property suite was run.
QuantLib, stochastic-path, calendar-dependent holdings P&L and spreadsheet
execution remain untested here. The original-layout entry-policy test is retained
as a reference. Private receipt: `.job-runtime/calculation/verification/copy-smoke.json`.

The intended later layering is job/script -> model/assumptions -> reviewed pure
calculation operators -> numerical backends. Source fetching, secrets, storage,
reporting and email stay outside operators. Treat enterprise value and expected
value as separate named quantities; physical probabilities and risk-neutral
option pricing must also stay explicit.

## Tools researched for a later validation stage

These are candidates, not installed by this change. Use public/synthetic cases
for external spot checks and keep private portfolio computations local.

| Tool/reference | Proposed use | Evidence boundary |
| --- | --- | --- |
| [Hypothesis](https://hypothesis.readthedocs.io/en/latest/) | Generate/shrink edge cases; financial invariants and transformations | Random/property coverage is not a proof over all inputs |
| [Decimal](https://docs.python.org/3/library/decimal.html) and [SymPy](https://docs.sympy.org/latest/modules/evalf.html) | Explicit money precision/rounding; exact rational and symbolic reference cases | More digits do not repair wrong conventions or input data |
| [MPFR](https://www.mpfr.org/) | Independent higher-precision floating-point reference | Correctly rounded operations do not certify an entire financial model |
| [QuantLib](https://github.com/lballabio/QuantLib) | Pricing/convention comparison when independently implemented | Match exercise, dates, rates/dividends and units; calling the same QuantLib backend twice is not an independent oracle |
| [NIST StRD](https://itl.nist.gov/div898/strd/general/howto.html) | Certified reference datasets for statistical/regression operators | Not a DCF, option or investment-model certification |
| [NumPy assertions](https://numpy.org/doc/stable/reference/generated/numpy.testing.assert_allclose.html) | Explicit absolute/relative tolerances, finite/shape/dtype checks | Disable equal-NaN acceptance where outputs must be finite; no blanket default tolerance |
| [mutmut](https://mutmut.readthedocs.io/en/latest/index.html) | Check that tests detect sign, fee, discount or boundary mutations | Surviving/equivalent mutations require review; coverage alone is insufficient |
| [pyperf](https://pyperf.readthedocs.io/en/latest/) | Bounded timing/memory benchmarks at representative and stressed sizes | Performance measurements do not establish numerical correctness |

Native web search and primary-source opening supplied the references. Specific
mpmath and QuantLib test-suite pages could not be opened; no successful opening
of those pages or local installation is claimed.

## Future numerical acceptance

For each adopted operator, freeze its domain, units/conventions, oracle,
absolute/relative or economic tolerance, error behavior and resource budget
before inspecting results. Check hand-solvable cases and an independent reference,
domain invariants, precision escalation, and relevant extremes. Include zero or
near-zero denominators, nonfinite data, cancellation, huge/small magnitudes,
rounding ties, long accumulation, missing/cross-currency inputs and boundary dates.
For options include expiry/low-vol limits, parity/bounds where applicable,
ill-conditioned IV inversion, dividends/exercise conventions and surface-support
boundaries. Stress both numeric domains and workload size; keep those results
separate. Formula correctness is distinct from model calibration or alpha.

Do not count a copied test or passing old suite as new independent validation.
Record skipped optional paths and gaps. Promoting or wiring an operator into a
runtime requires the workspace's [actual scheduled Codex E2E and verified result
email](runtime-acceptance.md), tied to that exact version. This copy remains an
inactive candidate until that separate acceptance is performed.


## Independent quality phase (2026-10-31)

The frozen `legacy/` manifest remains byte-identical. Independent checks live in
`shared/calculation/validation/`; maintained corrections are isolated under
`shared/calculation/operators/`. No production callers are migrated and no CRUD
service is introduced. Specialist frozen protocols declare numerical domains,
reference algorithms, budgets and tolerances before results. Original failures,
environment incompatibilities and later corrected variants remain in private
artifacts; they are not rewritten as first-pass successes.

### Local environment and reproduction

Prerequisite: Python3.12 on the host; macOS `/usr/bin/sandbox-exec` for the tested
worker boundary. Provision only a local venv, cache and temp area:

```sh
mkdir -p .job-runtime/calculation/tmp .job-runtime/calculation/cache/pip
python3.12 -m venv .job-runtime/calculation/.venv
PIP_CONFIG_FILE=/dev/null PIP_CACHE_DIR="$PWD/.job-runtime/calculation/cache/pip" \
TMPDIR="$PWD/.job-runtime/calculation/tmp" PYTHONDONTWRITEBYTECODE=1 \
  .job-runtime/calculation/.venv/bin/python -m pip install \
  -r shared/calculation/validation/requirements-lock.txt
PYTHONDONTWRITEBYTECODE=1 \
  .job-runtime/calculation/.venv/bin/python -B \
  -m shared.calculation.validation.runner --run-id unique-local-run-id
```

The direct requirements and resolved validation lock are separate from inherited
reference requirements. pandas2.2.3 is deliberately pinned: pandas3.1.0 produced
microsecond indexes while exchange-calendars4.11.2 compared nanosecond values,
causing false DateOutOfBounds. That failed environment receipt is retained.
The scheduler and broker environments are not changed. Reinstall on another
device; do not copy venvs or rotating auth. Linux/Windows sandbox parity is not
implemented; do not claim the macOS worker boundary there.

### Public acquisition and computation boundaries

Researchers retrieve only public issuer/SEC, Cboe and FRED data. Inputs are saved
with URL, retrieval/data-as-of dates, units, selection/extraction lineage and
hashes under `.job-runtime/calculation/validation/<suite>/`. Some samples are
explicit primary-page excerpts, not raw CSV/HTML. The FRED CSV attempt failed;
no independent CSV/page corroboration is claimed. Cboe is delayed and its raw
JSON timestamp timezone is undeclared. Microsoft CFO-minus-capex is a historical
cash-flow proxy, not automatically FCFF or a current fair-value forecast.

The calculation workers do not acquire sources. They receive a stripped
credential-free environment, private local HOME/cache/temp, pinned code and
public/synthetic samples. An inherited macOS profile denies network operations,
reads of broker/private archive/market-data credentials/Codex auth and other
runtime contents, and writes outside calculation state. Parent metadata needed
for symlink rejection is permitted. Python read/write audit checks add a narrow
allow-list; their restrictions alone do not propagate to fresh subprocesses.
The OS profile does propagate. Synthetic negative probes verify network denial,
private-runtime content-read denial and outside-state write denial before suites.

Keep ONLY public/synthetic data and validation environment/artifacts in calculation
state; never store credentials or private account data there. The OS profile uses
allow-default for required native-library/system operations with explicit denies;
it is not a universal hostile-code/container isolation claim. The model-host and
acquisition tools are separate from the offline worker boundary. CPU/wall time
and retained result-size budgets are explicit; no unsupported peak-memory limit
is claimed. A stricter initial OS read whitelist aborted native-library startup;
that failed probe is retained rather than reported as a working boundary.

### Numeric contracts and acceptance

Maintained valuation/holdings arithmetic uses exact rational accumulation and an
owned Decimal80 output policy, rejecting binary floats/bools and explicit size,
magnitude, vector and period over-budget inputs. Finite money/ratios remain
Decimal strings. Holdings checks survive Python optimization and leave inputs
unchanged. Maintained paths use owned Decimal100 contexts with explicit float
representation failure, exact probability-mass comparisons and bounded vectors.
Neither path weights nor analyst probabilities are silently calibrated.

Spreadsheet checks are bounded OOXML screening: external/error constructs are
rejected, missing formula caches stay unverified, and no formula is executed.
Cached values alone never prove formula correctness or DCF model validity.
Options diagnostics retain their stated European/American, flat-vol and surface
support limits. Extreme tiny values may lose relative accuracy while remaining
inside the predeclared absolute budget; warnings must remain visible.

The runner writes source/protocol/sample fingerprints and per-suite results under
`.job-runtime/calculation/runs/<id>/`. Each run ID is exclusive; never overwrite
an earlier trial. The manifest verifier still verifies the frozen copies only.
Scheduled acceptance uses a future one-time allocation of the existing shared
job runtime and the component completion adapter. The actual Codex session runs
these offline checks and a supervisor independently verifies the receipt and
sends the owner result email. This must be described as supervisor-sent. Scheduled
harness completion, numerical acceptance, remaining baseline defects and model
calibration are separate statuses. No daily production email cutover follows.


### Coordinator preparation and final boundary checks

The coordinator prepares one synthetic noncredential sentinel outside the
calculator model's write scope at `.job-runtime/calculation-denied-canary.txt`.
Its exact content is `SYNTHETIC_NOT_A_CREDENTIAL`; create with exclusive mode0600,
verify an existing file rather than overwriting it. No actual credential file is
opened by the negative probe. The runner never creates/deletes outside its own
writable state; absent/mismatched sentinel stops acceptance.

The final calculator business profile explicitly grants ONLY `.job-runtime/calculation/client`
plus the executor's own ephemeral working directory. It has no implicit Niulai
grant. Coordinator declarations under `.job-runtime/acceptance/` remain outside
that writable scope; per-attempt result indexes live inside calculator state.
The first scheduled trial's configured write-root mismatch is preserved as a
failure and requires a distinct new trial after restart.

Actual interpreter/binary digest and installed distribution versions are attested
before and after runs, checked against the resolved lock and frozen coordinator
fingerprint. The worker profile denies writes to its venv, source captures and
sandbox policy in addition to the earlier network/private/write bounds. Streaming
stdout/stderr accumulation is stopped at 2 MiB and timeout/overflow processes are
killed/reaped; synthetic negative tests cover both paths. This bounds retained
pipe memory, not total numerical-process memory. Scheduled completion checks read
actual durable claim time and enforce the predeclared start-lateness limit,
completion deadline and current-attempt result paths/digests.


### macOS Codex sandbox integration: attempt-scoped request bridge

The second actual scheduled trial reached the runner but macOS refused nested
`sandbox-exec` with exit71, sandbox_apply Operation not permitted. A separate
Codex-session diagnostic confirmed this limitation. Both failed scheduled trials
are retained; local shell success never replaced them.

The final allocation uses `shared.calculation.validation.acceptance:prepare` and
`:verify` around the normal business executor. `prepare` starts one bounded,
attempt-scoped host thread, outside Codex's tool sandbox. The Codex session runs
`shared.calculation.validation.client` to submit one fixed context/source-bound
request and waits for its response. The host launches the same restricted
workers and returns the report. This is an explicit computation-tool interface;
no results are computed before Codex requests them and no additional persistent
daemon or network listener is required. The request is bounded and exclusive;
replaying the same pending request waits for the same result, not another run.

The original OS private-read/network/write protection remains on workers, including
fresh child Python interpreters. No Python-only isolation fallback is used. The
host applies its policy from an immutable in-memory string so editing its writable
diagnostic copy cannot change worker permissions. Trusted host memory retains the
actual result digest for completion verification, independently of model-written
state. Coordinator declarations remain outside the model write grant. Ten boundary/
malformed-request regression tests and a separate real component request-flow test
verify these mechanics; neither is itself scheduled acceptance. Service restart
is required when adapter Python code changes because modules are cached.


The final bridge grants Codex write access only to the request inbox, not the
host-owned inputs, environment, bridge responses, reports or indexes. Host reads
use anchored directory descriptors and O_NOFOLLOW; nonblocking regular-file,
single-link, owner and size checks reject symlinks, hard links and FIFOs before
consuming a request. Host result digests derive from in-memory canonical report
bytes, not a potentially edited file reread. Existing host output paths are
contained and checked for symlink ancestors. This scope separation protects the
trusted host from model-writable parent-path substitutions.


### Verified quality-phase result

The final one-time scheduled Codex request/host-worker flow completed on 2026-10-31.
The durable claim started 3.212 seconds after due (inside the predeclared 15 seconds),
with one attempt, completed Codex transport and independently verified host
postconditions. The actual receipt grants only the client inbox. Source, all
public captures, 27-distribution environment and interpreter bindings remained
unchanged; all 4 worker suites completed with 3 negative security probes passed.
Earlier write-scope and nested-sandbox scheduled failures remain preserved.

Corrected valuation/holdings passed 217/217 cases, including all208 original
criteria; legacy retains 8 failed cases. Options passed 4,180 checks, retaining 2
extreme tiny-value relative-accuracy warnings within the frozen absolute budget.
Paths passed all 8 corrected-operator checks; its combined 34 groups retain 3 legacy
failures, with 625 declared input cases. Spreadsheet/stock contracts passed 30 groups
and retain 2 legacy validator failures; 29 unchanged inherited P&L tests and 4 new exact
P&L cases / 3 boundary cases are labeled separately. These counts are not independent
statistical samples and do not establish general calibration or alpha.

Private human-readable proof: `.job-runtime/calculation/reports/quality-20261031.html`;
raw reports and attempt records remain under calculator/runtime private state.
Owner email synchronization is recorded separately with exact mailbox readback.
The frozen originals remain byte-identical; corrected operators are not wired
into production. No general calibrated probability surface or executable-fill
historical replay engine is introduced.


Owner notification was accepted and exact subject/recipient/HTML verified by
Gmail readback. The private receipt records the message ID and verification time;
public docs contain no owner address or private account data. All completed
calculator one-time allocations are disabled after verification; durable
attempts/results remain intact. Mainstream calculation imports and production
email ownership remain unchanged.
