# Synthetic holdings atomic test evidence

2026-11-15. Implementer evidence, awaiting separate verification and the owner's
URL/cloud checks. The current worker had no actual `MENTOR_INIT_OK` output;
`mentor/AGENTS.md`, `mentor/ROUTING.md`, development-discipline and the installed
backend-testing-skill-set/core-workflow/exception-safety were read directly.

The independent contract is atomic-contract-v1.1. Its acceptance SHA256 is
`e374cc970c7e4d24ad8ae11fe8689672a492acec4d5db9beece8e8fdf041e453`; the independent
case JSON SHA256 is
`bffd7b0217b07b6c0c5c7a2384d5afcb1cd7ca455f0cca27951f929f7c5e1d78`. The implementer
did not edit either artifact. The designer's recorded amendment clarifies actual
STK/OPT/FUT/FUND types, cash as an asset amount, and requested-scope completion
separately from whole-portfolio evidence. No behavioral requirement was amended
by the implementer.

The owned change is inert/local. It adds no dependency, activation, server,
provider, model, broker, email, scheduler or global configuration. Root owns
Agent Server/API wrappers, cloud writes/readback and URL self-testing. The
maintained `niulai/holdings/analytics.py` is reused without modification; its
recorded SHA256 is
`02d4fd02b9b144deaa508989d3e5d2aeac17108fc0e25268b491a0e312ce7111`.

The adapter now rejects malformed contract/currency identities and canonicalizes
option strike/right identities. It preserves exact monetary sums beyond the
default Decimal precision with a bounded local context, and restores the caller's
context. Missing, invalid and nonfinite measurements remain unavailable; extreme
numeric expansion is rejected. Quote observations are optional explicit
caller-supplied metadata, with an inclusive cutoff and a quote timestamp no later
than query completion. Absent quote time/policy stays unknown. Optional checkpoints
must be committed and bind the exact supplied receipt hash/attempt; neither hashes
nor matching labels prove authentication or a live read.

The pure graph invokes the actual `analyze_admitted` function through the
`portfolio_analysis_tool` StructuredTool, propagating RunnableConfig. Native tool
start/end/error spans belong to the `portfolio_analysis` node. Public projection
retains exact monetary strings and rounds its four rate/percentage metrics to
12 decimal places with ROUND_HALF_EVEN. Full analysis retains high precision
Decimal strings. The original eight public cases and their outputs remain
compatible; the roster has 26 selectors, including all six exact independent
HOLD public aliases. Its content SHA256 is
`ffc980228889b985c751f9e85d853984640a9c17e7f4893bf81fcf84519af513`.

Run from the workspace, with the existing local environment:

```sh
LANGSMITH_TRACING=false PYTHONDONTWRITEBYTECODE=1 .langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.verify_holdings_tests
```

The final run passed **168 tests, zero skipped, zero failures/errors**: 16 original
controls, 91 boundary/arithmetic/metamorphic/tracing tests, and 61 independent
contract tests (HOLD-01–60 plus artifact/completeness integrity). The same 168
tests passed after all temporary mutation patches were restored. This repeat
checks patch restoration; it is reused evidence, not 168 additional independent
samples. Every frozen HOLD case has its own executed test ID. The evidence JSON
contains exact test IDs, criterion mapping, source hashes, error output and all
mutation variants.

Final evidence: `.langchain-pilot/runtime/portfolio/579ab2ff-812c-41b3-b38c-8a5e124bd6da/holdings-tests.json`.

Fourteen bounded in-memory deliberate breaks ran. Thirteen were killed: failed
empty as success; count mismatch ignored; account match skipped; duplicate
identity removed at both layers; missing value defaulted to zero; query time used
as quote time; absolute net exposure; default Decimal precision rounding money;
unrealized PnL used as daily PnL; unknown checkpoint accepted; an old success
substituted for analytics failure; native tool callbacks bypassed; and arbitrary
public selectors accepted. Removing only the adapter's duplicate identity guard
survived the public-outcome control because maintained analytics plus the adapter's
post-build integrity gate still reject same-currency duplicates. This is classified
as enforcement at a second layer. Removing both layers is killed. There are no
unexpected survivors. Cross-currency contract duplicates are separately rejected
by the adapter's account-wide identity rule.

All tried local variants were retained. The earlier evidence at
`c9a8c7cc-7a34-405c-9f49-a527d3a1c6d0` passed 165 tests and reported 13 kills from
a stricter pre-analysis spy test; it did not demonstrate the second-layer public
outcome. The replacement public-outcome mutation control at
`2aa2de69-669d-4433-9eb9-bfaa59ba5676` passed 165 tests with 12 kills/one classified
survivor. Evidence at `997ce767-38dd-4d66-a9c0-6f8066138b6d` passed 168 tests with
12 kills/one classified survivor. The final run adds the default-precision monetary
control, producing 13 kills/one classified survivor. These are development
iterations, not separate acceptance trials.

Criterion coverage: AC-015–025 all have their frozen HOLD cases; additional local
controls cover AC-011/012 tool parentage/error outcomes, AC-013 pre-callback selector
fencing/closed diagnostics, and AC-030 original roster compatibility. Required
Agent Server discovery/schema/run/state, exact URL/listener provenance, isolated
cloud trace/resource/feedback readback and independent verification are **NOT RUN
by this worker**. They remain owned by root. No real future scheduled Codex session
or synchronized acceptance email ran, so major-runtime acceptance is unverified.

Residual limits: inputs and quote cutoffs remain caller-supplied/unverified;
partial retrieval is rejected with explicit missing-type gaps rather than used for
partial useful analytics; local graphs establish neither persistence/restart
durability nor real account/quote freshness. No historical fixture, private account
state, credential, live brokerage call, order or email was used. These synthetic
tests do not establish investment quality, alpha, production acceptance or
autonomous model dispatch.
