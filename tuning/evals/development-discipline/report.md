# Development discipline screening — 2026-10-30

The new workspace-authored skill and six-skill router passed the frozen bounded
adoption rule. They are a **provisional procedural default**, not an automatic
release barrier. General effectiveness remains inconclusive.

| Measured outcome | Existing five-skill routing | New selective routing |
| --- | ---: | ---: |
| Decision-quality rubric, four cases | 30 / 32 | 32 / 32 |
| Observed critical failures | 0 | 0 |
| Correct routes, including two controls | 6 / 6 | 6 / 6 |
| Sum of separate-decision instruction-token proxies | 32,924 | 28,356 |
| Cumulative session instruction-token proxy | 14,551 | 14,273 |

The new skill itself adds 1,090 proxy tokens when loaded. Separate-decision
context is 13.87% lower than the existing router because focused engineering
decisions can use the small local skill. Cumulative session context is only 1.91%
lower: earlier loaded skills remain in context. Against the counterfactual of
loading all six on every decision, selective loading saves 70.05% in separate
decision snapshots; cumulative session savings are 9.54%. That counterfactual is
a cost calculation, not a third quality arm. These figures are `o200k_base`
serialized text proxies, not provider token usage, billing, latency or memory
measurements. Host instructions, reasoning, tool framing and caching are excluded.

| Engineering decision | Baseline | Candidate | What the grader distinguished |
| --- | ---: | ---: | --- |
| Provider capability before framework | 7 / 8 | 8 / 8 | Candidate explicitly named the atomic capability before the narrow E2E; baseline proceeded directly to the E2E. |
| Partial publication, exception leak and unknown outcome | 7 / 8 | 8 / 8 | Candidate explicitly bounded transient retries; baseline bounded query/startup timeouts but left transient retry policy unspecified. |
| Correlated signals, reused tests and hindsight | 8 / 8 | 8 / 8 | Both refused a proven-alpha claim and proposed matched, cost-aware confirmation. |
| Supported narrow offline integration | 8 / 8 | 8 / 8 | Both accepted the demonstrated slice and deferred speculative framework work. |

The quality difference is small and mostly explicitness of useful next steps.
These were artifact-based advisory decisions, not implementations or independent
execution evidence. The score gap does not establish that resulting software
fails less often. In the acceptance case, supplied evidence covered 200 records
while mentioning a 500-record requirement. Both workers correctly limited
acceptance to the demonstrated slice and requested one bounded capacity check;
the grader accepted that scoped decision without demanding speculative scale.

## Execution and review

Protocol, cases, router and skill were frozen before responses. Two fresh workers
received the same six public synthetic cases, identical inherited model/settings
and a 220-word cap. Each wrote per-case routes before loading its selected local
skill snapshots. The new route loaded development discipline for four engineering
decisions, combined it with recovery/evidence/experiment/evaluation when needed,
and skipped it for a release-note summary and a grader-only correction.

A third fresh worker graded eight anonymized, shuffled engineering responses.
It passed a two-anchor calibration before writing grades. All eight scored
responses had four literal supporting excerpts and valid scores. Root review
checked arithmetic, artifact support, critical errors and the disputed scope of
200 versus 500 records; it retained the raw independent grades. Both solvers
completed every case within the cap. No solver quality reruns or post-result
skill edits were made. All raw responses, routes, snapshots, hashes, anonymization
key and grades remain in ignored `tuning/runtime/development-discipline-v1/`.

The executable aggregation gate checks source/snapshot hashes, complete unique
case IDs, response schema, unchanged route choices, known evidence IDs, literal
grading excerpts, rubric ranges, calibrated anchors and the frozen adoption rule.
It exits unsuccessfully on invalid artifacts or a failed adoption rule. Its
regressions cover missing/duplicate data, duplicate JSON keys, non-finite scores,
invented sources, false grade quotes, route changes, unnecessary control loads,
case regression and critical defects despite lower token cost. These are tests
of the evaluator, not of natural-language obedience. The complete mentor suite
also retains the upstream validators and source-bundle checks.

## Limits and next use

The cases and rubric are author-created visible development material, not
protected holdouts. There is one worker per arm, with all six cases in that
worker's context, so within-arm carryover and stochastic variability are not
estimated. Grading uses the same model family; anchor success is not human
calibration. File restrictions were instructions rather than an OS-enforced
boundary. No private state, financial holdouts, live provider calls, host
activation or actual investment outcomes were used.

Mandatory root routing and the evidence procedure are implemented. No independent
watchdog, CI hook, automatic secret scanner or production promotion lock was
installed. Actual fault/security regressions belong in the affected component.
Use this skill on the next real development task and retain actual contract,
E2E, fault and cost evidence before making broader reliability or ROI claims.
Do not tune on this screen and relabel its cases as fresh confirmation.

## First real development smoke check

The separate UI-skills integration applied this procedure to a real workspace
change. It kept guidance, pinned CLI adapters, tuning metrics and a synthetic
React verification fixture separate; optional Motion/Magic UI MCP activation was
deferred. Review found a pending-save/newer-draft risk and a macOS Playwright
daemon path that ignored the general cache override. The fixture now prevents
editing a pending draft, and the CLI adapter explicitly localizes its daemon.
Rendered regressions check draft/operation identity rather than a success toast
alone. The passing full-Chromium run records eight tests, zero skips, failures or
flaky retries; prior sandbox-startup and headless-shell runtime failures remain
preserved. See the frontend runbook for the exact tested paths and limitations.

This is useful execution evidence for those UI contracts and recovery decisions,
not a matched baseline experiment proving that the mentor skill caused them or
that all future implementations are safe. No investment application was changed
by this synthetic fixture.

See `protocol.md`, `cases.json`, `results.json`, `prepare.py` and `summarize.py`;
the component deployment runbook documents local environments and reproduction.
