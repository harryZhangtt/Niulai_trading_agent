# Lightweight UI intent card evaluation

This is a bounded, exploratory classification screen before any global installation.
The proposed benefit is fewer instruction tokens with no observed loss of correct
intent selection. It does not measure execution quality of the expert skills.

The baseline is exactly `ui/ROUTING.md`; candidate v1 is exactly
`ui/portable/INTENT-CARD.md`, initially frozen at
`272d6e628966098b579ec1756e2c34f02af51dfd8f51bd17d04d8f1ede7ff6f7`.
Both receive the same classification control, decision enum/schema, task batch,
configured model/profile, tool restrictions, and resource ceiling. No expert full
bodies, expected answers, or case criticality enter classifier prompts.

The 24 development requests and 12 fresh validation requests in the two JSON files
are synthetic, authored before model results. Cases cover unnamed real intents,
new direction versus existing polish, layout, components, React races/performance,
GSAP subtopics, extraction versus redesign, unavailable Pencil tools, explicit
style choices, negative/backend lookalikes, untrusted quoted content, separate
variants, and genuine missing-context or conflicting-authority clarification.
Most prompts do not name a skill; explicit product/style/library names remain
when necessary to test user-selected authority or framework behavior.

Gold declares required/optional decisions, clarification, resolver status, and
separate variants. Host grading expands decisions to skill sets with dependencies.
Equivalent redundant labels that load no extra body are not semantic failures.
An optional route is allowed, not rewarded; optional loaded skills are reported.
Every case requires exactly one plan except declared clarification (zero plans)
or two separate variants. Required skill omissions, unneeded skill bodies, wrong
clarification, conflicting authorities, wrong variant partition, duplicate route
labels, and resolver-status mismatches fail strict correctness. Resolver success
alone never establishes intent correctness. Pencil availability is caller-declared,
and the classifier cannot prove tool execution.

The host uses the existing `evidence_runtime/contracts.py` sealed contracts before
dispatch and before/after scoring. The sealed source closure includes the complete
roster/gold, grader, runner, profile fingerprint, card/policy and resolver/catalog.
Every attempt is claimed once before work; results, errors and unknown usage are
preserved. Model traces use `.job-runtime/evaluations/ui-intent-lightweight-20261102/`;
the existing contract ledger uses its allowlisted ignored `.research-sources/`
root; sanitized reports and prompt hashes use `tuning/runtime/`.

Initial ceiling is four real model calls: development baseline then candidate,
followed only after root review/final freeze by validation candidate then baseline.
Both arms use the existing default profile unchanged, currently requested
`gpt-6.1-sol`, reasoning `low`, timeout 120 seconds. Each batch permits one call,
120 wall seconds and 100000 observed input+output tokens. Total stop is 300000
observed tokens. There is no automatic retry or model fallback. Busy auth cache,
authentication, unavailable model or transport failures stop real dispatch;
an incomplete pair is inconclusive. Every attempt, including failed/unknown ones,
remains visible. A changed candidate starts a new sealed version; validation is
never used to tune it. Four calls cannot identify stochastic or order variance.

The output is only `cases[{id,needs_clarification,plans[{decisions:[]}]}]`, no
rationale or duplicate skill list. Report strict correct cases, critical misses,
missing/extra/optional skills, precision/recall and clarification separately from
latency and usage. Preserve provider-reported input, cached input, output and any
reasoning counters exactly. Missing fields stay unknown; no dollar cost inferred.
If a local tokenizer is already available, serialized instruction/prompt counts
are explicitly nonbilled proxies excluding host overhead and caching.

The candidate supports this screen only if there are no observed critical failures
and its strict correctness is at least baseline in each completed split. This
deliberately conservative gate is for a local packaging decision, not a statistical
claim of superiority. Missing/invalid evidence is inconclusive; an observed
critical violation rejects that candidate under this gate. Report noncritical
misses even when baseline also misses. Small synthetic, correlated batches, one
configured model and one run per split cannot establish general reliability.

Fresh classifiers have tools disabled and receive no expected answers. Shared
filesystem packet separation is not an OS-protected holdout; the authoring agent
has seen gold, so its own independent screen is explicitly unblinded and nonbilled.
Validation is fresh to root/candidate editing until final freeze, not a protected
benchmark. If real model measurement fails, subagent behavioral inspection and
tokenizer proxies can still be delivered with this limitation and unknown actual
usage. No scheduling, external messaging, global installation or runtime
acceptance is performed; manual evaluation does not satisfy the future-session
major runtime acceptance policy.
