# Development discipline: quality and routing screen v1

Freeze this protocol, cases and skill before responses. This exploratory screen
asks whether a sixth, local development skill improves artifact-based decisions
without making every request load more guidance. It is not a protected investment
holdout or proof of implementation reliability or financial alpha.

Compare the existing five-skill router (`baseline-routing.md`) with the six-skill
router and new skill. Both get the existing mentor core, identical synthetic
artifacts, model/settings, 220-word limit per case and tool boundaries. Two fresh
workers receive only their arm's packet and an allowlisted skill snapshot. They
select routes before reading selected skills. No gold keys, previous results or
conversation history. Worker packets contain all six cases: within-arm context
carryover is possible. Restrictions are instructions, not an OS access sandbox.

Four engineering decisions cover: premature abstraction versus atomic E2E;
partial publication/unknown external outcomes/exception leakage; correlated
signals and reused tests; and accepting a well-supported narrow integration
without demanding speculative improvements. Two controls cover a plain summary
and grader-only work. These author-created public development cases are not blind
holdouts. No private state, provider calls, host activation or model changes.

Primary quality is a defensible decision grounded in supplied artifacts and a
concrete next step, not checklist wording. Four case-specific criteria per
engineering case score 0 (absent/wrong), 1 (material gap), 2 (concrete and correct).
Keep case results and critical defects visible; never compensate for a critical
failure with lower token cost. A separate fresh grader receives anonymized,
shuffled answers and case rubrics, no arm labels or skill text. It must first pass
an obvious good/bad anchor pair. The root checks evidence, arithmetic and critical
failures. Same-family judging remains a limitation. Do not demand a preferred
implementation when another satisfies the artifact invariants.

Routing checks required/optional skills frozen in `cases.json`. Report misses and
unnecessary loads separately, including negative controls and overlapping routes.
Expected routes differ by arm because the baseline lacks the new skill. Measure
serialized task-specific instruction, case and response sizes with pinned
`tiktoken==0.12.0`, `o200k_base`, using only a workspace-local cache. Count full
selected entrypoints and their required local investment contexts, and count the
union for the sustained session (loaded text remains loaded). Compare selective
loading with the cost of loading all six skills; that is a cost counterfactual,
not a measured quality arm. Report available provider usage separately; absent
telemetry stays unavailable. Proxy tokens exclude host instructions, reasoning,
tool framing, caching/billing and are not dollars or latency.

Preregistered bounded adoption rule: candidate has no critical failure, no
engineering case below baseline, all required routes and no unnecessary skills,
and lower aggregate instruction proxy than always loading all six. Controls must
avoid the new skill. Quality improvement is unproven if tied or otherwise too
weakly supported; the rule permits only provisional procedural routing, not a
claim of general effectiveness. Missing outputs/grades make the screen incomplete.
Observed quality failure rejects that version for this rule. Preserve all runs;
do not tune on these cases and relabel a rerun as fresh validation.

Budget: two solver workers, one grading worker; no quality retries. One format-only
repair is allowed with the failed output retained. Root performs deterministic
artifact validation. Stop after this screen and report limitations. Each worker
inherits the parent model/settings; no model override. The independent worker
pass follows the installed skill-creator's forward-testing instruction.

Reproduction uses the existing local validation Python (standard library plus
optional pinned tokenizer); see the mentor section of the component runbook.
`prepare.py` freezes versioned packets under ignored
`tuning/runtime/development-discipline-v1/` and refuses overwrite. `summarize.py`
validates captured responses/grades and reports quality and context separately.
Neither calls a model. Real runtime failure/security tests still belong to the
affected component. This procedure is not an installed CI or release hook.
