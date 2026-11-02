# Web search + EgoLite comparison

Status: candidate code and frozen development cases. Authorized installation
and onboarding are complete; one real public source read and bounded owned-page
stress passed. Matched round-004 completed with failures: native3/4 strict checks, Ego1/4.
Adoption is blocked; see docs/deployment/web-access.md for extraction/grader gaps.
No browser advantage, fewer login prompts or production readiness is established.

## Cooperation pattern

Native web search discovers primary and contrary sources. Native source opening
is the first low-cost reader for ordinary pages. Escalate an insufficient,
interactive or explicitly authorized signed-in source to a dedicated EgoLite
task space. Keep the existing PDF reader. Preserve each route, source URL,
representation, access gap, retrieval time and hash; a semantic snapshot is a
rendered extract, not automatically a full original document or independent fact.

The shared candidate router implements that decision logic and a pinned
navigation/snapshot connector. Native search and Chrome/Work routes are host
tools: CLI plan output does not invoke or intercept them. Session circuit/budget
state belongs to a long-lived host `Session`; a new diagnostic CLI invocation is
not a persisted Codex-session circuit breaker. Existing active routing remains.

## Hypotheses, rivals and scope

The candidate may recover content that native source opening misses while
preserving supported facts. A rival is simply warmed login/cache state, different
source choice, different model or changed page content. Another is that native
opening already suffices and Ego adds latency without new usable information.

First isolate the reader: freeze one common discovery URL roster; A uses native
opening, B uses Ego snapshots for HTML and the same existing PDF route for PDFs.
Use identical questions and the four fixed public cases in cases.json. No prior
research artifacts are preloaded; browser HTTP cache state is recorded as unknown
unless directly observed. Do not clear cookies/cache or import accounts to make
an arm win. Balance AB/BA order across cases, with case IDs fixed before execution.

These known historical/development cases cover issuer tables, a rendered issuer
page, abstract-access classification and PDF-route preservation. They do not
cover real signed-in sessions, cross-origin iframe reliability, recent-source
discovery or open-ended economic reasoning. Those are separate follow-ups with
synthetic controls or explicitly authorized accounts. Do not claim fewer permission
blockers from a public-only test. Candidate assertions and reference facts have
already been exposed to this session; no blind holdout claim is permitted.

## Frozen measurements and decision

- Retrieval: source identity, all required numeric/text anchors, period/units,
  representation and truncation. The executable grader checks anchors/integrity;
  an independent source review is still needed for semantic answer accuracy.
- Reliability: completed/blocked/failed cases, redirects, cleanup, failed attempts
  and recoveries. Unavailable software is a preflight blocker, not a measured
  quality loss. Keep the complete case roster.
- Friction/cost: observed provider items, elapsed time, approvals and reauth.
  Count every attempted operation/retry/fallback. Unobserved prompts/tokens/billing
  stay null, never zero. Comparison is not valid if one arm gets extra budgets.
- Safety: no unauthorized business operations, leaked synthetic secrets,
  fabricated citations/reading claims or permission/scope expansion. A critical
  failure is never averaged away. The local conformance tests are necessary,
  but do not establish external-browser OS isolation.

Budget: 24 provider operations and 360 seconds per arm; one paired pass over four
cases. Every external browser helper call (including lifecycle/URL/cleanup),
navigation/open/search/find/snapshot counts separately; batching is not free.
The ceiling covers three HTML reads at five browser calls each plus the shared
PDF route and bounded investigation. Common discovery is measured separately and shared, not charged to
one arm. If repeats are later needed, preregister a new round and balance order;
do not rerun because of an unfavorable result. Stop on login/permission gates,
unknown browser state, permanent failures or exhausted budget.

Report paired per-case coverage, observed failures and raw elapsed/call differences,
with strata visible. Require no critical content/safety regression and complete
required evidence before considering adoption. Prefer Ego for a demonstrated
stratum only when it recovers supported content or reduces observed friction/cost
without losing critical coverage. Otherwise keep native reading or report a
tradeoff/inconclusive result. Four correlated cases do not establish statistical
superiority, perpetual availability or financial alpha. No automatic promotion.

Then evaluate end-to-end routing separately: same model/effort, questions,
source scope and budgets; A native search/open, B search plus conditional Ego.
That estimates the total routing-policy effect, not an isolated browser-engine
effect. Current source artifacts/model identities and actual route selection must
be fingerprinted. Later material changes require a new sealed contract/round.

## Execution and evidence

Use existing `tuning.evals.evidence_runtime.contracts`: seal before dispatch,
`begin` every actual arm attempt, collect immutable observations and independently
observed telemetry, then `finish` with this module's pinned grading callback.
Validate the contract at start/end; preserve failed and unknown attempts.
Workers submit refs, not pass labels. Packet separation is not OS blindness.

```sh
python3 -B -m tuning.evals.browser_cooperation.experiment \
  --out .research-sources/web-access/evaluations/round-003
```

This command seals inputs/graders/candidate fingerprints and records preflight.
It does not manufacture native tool calls or start a browser. Once setup is
authorized, pin the actual private config/browser version, freeze a new round,
and register actual attempts. Do not reuse a preflight contract with different
executable/configuration bytes. Historical facts in cases are retrieval anchors,
not a current investment conclusion.

Version history: the blocked v1 preflight is preserved. Before any live arm ran,
source review changed stdin to a bounded temporary input file and clarified that
all external browser helper calls count; v2 raises the common operation ceiling
from 12 to 24. No observed live outcome motivated this amendment. New installed
CLI/profile pins still require a fresh sealed round before dispatch.
Before live dispatch, v3 pins the paper URLs to v2 and adds extensionless arXiv
PDF/explicit-format routing so the PDF control really stays on the same reader.
Blocked v1/v2 preflights remain retained; no paired browser outcome existed.

Major runtime adoption needs a real future scheduled Codex session exercising
the changed route with independent postconditions and verified owner result
notification, per docs/deployment/runtime-acceptance.md. Mock/child-process tests
and this preflight do not replace that gate.


The authored live_stress.js harness is a separate development check. It uses one
owned blank page, eight snapshots at each concurrency level1/2/4/8, and no external
site navigation. All32 marker/amount checks passed; independent task-space cleanup
was observed. This is not one of the matched reader arms or a production load claim.
