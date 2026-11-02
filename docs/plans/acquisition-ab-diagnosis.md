# Acquisition A/B diagnosis

This read-only diagnosis checked the retained run artifacts and current source
code. No old result was rewritten, no new web/model call was made, and no key was
read. The central finding is a mismatch between the question being asked now
(information richness/freshness) and the quantity measured by the old NOW test
(correct interpretation of a fixed evidence packet). The SaaS web comparison
used live discovery, but the cache/retry/fallback infrastructure was not invoked.
These are different limitations; neither proves the data pipeline is inferior.

## What the old tests actually did

| Test | Actual intervention | Acquisition evidence | What its result supports |
| --- | --- | --- | --- |
| NOW contribution | Structured contribution instructions/host validation versus competent generic analysis, using the same captured packet | All eight pairs had identical `packet_ref` and embedded request packet; both arms executed zero actions in every case | Contribution/definition/forecast discipline on that fixed evidence, not discovery breadth or freshness |
| NOW captured regrade | Mechanical grader binding repair over unchanged answers/reviews | Zero new source/model calls; original failures retained | Repaired grading of captured outputs, not a new acquisition experiment |
| SaaS web A/B | Existing add-on workflow versus normal native web search/open | Both arms: six query items and six open items. A: 12 tool calls; B: five batched calls. A: three local readiness rejections, zero readiness HTTP requests | Descriptive as-available workflow comparison. Cache, retries, fallback, paper tools and MCP were unused |
| Information-fetch richness protocol | Proposed acquisition experiment and temporal preflight | `status=design_and_preflight_only_not_a_sealed_or_dispatched_AB` | A plan and preflight, not a completed acquisition A/B |

The retained NOW case/pipeline receipts were re-read and hash-checked. These are
**packet hashes**, not independent source counts:

| Case | Shared A/B packet SHA-256 | A actions | B actions |
| --- | --- | ---: | ---: |
| `acv_target` | `1cf3781dfe25a4804ead351483e732bc5e4054c55ff0dc6a08e5d93cc031d5d7` | 0 | 0 |
| `forecast_q2` | `785db55dd62add648f017b3686c2b17465797c8e6c575d0cc1b235128003f07a` | 0 | 0 |
| `historical_vintage` | `fc1ea807497eead6b84656d70a06ca771f7873b3a2d9b3c7916c27169e8a6c28` | 0 | 0 |
| `launch_scope` | `879028e16e84affe30b400875321941758eab0d24185f0adb69744543d304d89` | 0 | 0 |
| `margin_counterevidence` | `c6c1981cac26101e11f76c2c084ce8d9990a345c245493f904467a660fd26df7` | 0 | 0 |
| `meter_already_known` | `d6c625cd91b676bd1373e2c82214279e782a2f15fcdbe68c57d57bd83d6ff6f2` | 0 | 0 |
| `meter_refinement` | `008420059675ceaf658ae12dc4b2db7891d6963387d27b3701b47674f005dbd2` | 0 | 0 |
| `usage_entitlements` | `1cf09f1fefcbc765bcc083f1ffbc294b8b54743dd96448cbefa8313054ce6ccb` | 0 | 0 |

Actual receipt roots are the ignored research-source runtime directories
`now-contribution-e2e-20261031/round-v1.0.1/record.json` and
`saas-web-ab-20261031/arms/{A,B}/trace.json`. They contain private paths and raw
tool transcripts and are not copied into this document or the public UI DTO.

## Exact source evidence

- `tuning/evals/now_contribution/protocol.json:10` fixes retrieval and the source
  packet; `:24` sets provider-source calls to zero. `:42` defines novelty score 2
  as a correct new/refined/known/contrary classification. It is not two new units.
- `tuning/evals/now_contribution/run.py:42` seals the same per-case packet input;
  `:72` passes the same case into both arms; `:131` records zero provider calls.
- `investment/research/contribution_run.py:32` reads that packet; `:36` sets zero
  actions and `:38` permits no actions. The only arm change is objective and
  finalizer, beginning at `:33` and `:40`.
- `tuning/evals/now_contribution/prepare.py:55` selects six original captures;
  `:117` builds excerpts before dispatch; `:153` explicitly allows reconstructed
  history; `:155` freezes each worker packet and `:158` discloses its limitation.
- `tuning/evals/now_contribution_regrade.py:1` states that answers/reviews are
  unchanged; `:51` budgets zero model/source calls and `:62` preserves the repair
  scope. Both captured regrade arms have novelty `[2,2,2,2,2,2,2,2]`. Their supported
  fact counts are A 21 and B 24, but sentence splitting differs over the same
  evidence. Those counts are not deduplicated information richness.
- `tuning/evals/saas_web_ab/protocol.json:18` pins the same native backend;
  `:29` sets 12 provider items. `:44` forbids interpreting different backends as
  an isolated add-on effect.
- `tuning/evals/saas_web_ab/inventory.json:3` calls routing instruction-only;
  `:5` records no native/default-action cache integration. `:9` records the CLI
  web-search limitation. The inventory's preflight rejection count is six;
  actual arm-A trace counts are three, as reported in the result document.
- `tuning/evals/saas_web_ab/report.md:83` records three pre-network URL rejections;
  `:88` lists unused action/cache/paper/MCP paths; `:95` separates batching and
  query choice from infrastructure overhead. `:104` preserves the original
  `EVAL_SOURCE_CHANGED` formal failures. The observed recent-requirement coverage
  was A 6/6 versus B 4/6 (`:39`), not a finding of zero observed coverage gain;
  its causal attribution and formal acceptance remain limited.
- `tuning/evals/information_fetch/protocol.json:4` explicitly says design/preflight
  only; `:37` lists the richer acquisition metrics that were not measured by NOW.

## What the new batch component fixes, and what is still missing

`shared/research_sources/batch.py` now composes configurable acquisition,
Cache/Store, bounded registered actions/discovery fetchers, failure receipts and
immutable execution snapshots. This makes cold/warm calls, failures and actual
fallback/retry use observable. It does not make a configured old URL newer or
turn a source catalog into an automatic discovery loop.

`investment/research/datasource_query.py:88` still starts from captured `S01`.
`investment/research/examples/datasource-query.pipeline.json:6` permits one action;
`:16` is a local `evidence.read`, and `:34` permits no additional actions.
`datasource_query.py:212` compiles questions into a catalog and `:223` publishes
one source. It does not execute those question nodes as new searches. Likewise,
`information_catalog.py:64` exposes capability readiness as not checked and
`:72` limits its scope to question planning.

The next useful connection is therefore: question plan -> actual search/open ->
versioned captured sources -> independent economic-unit review. The batch layer
can supply acquisition/cache execution and receipts once real discovered URLs
or a host search adapter are connected. A host-native search capture imported
into storage must remain labeled import/replay; it cannot be counted again as a
new provider fetch merely because it missed a local cache.

## One narrow acquisition workload

Use one NOW question about what newly establishes or fails to establish the
chain from AI use/meter to purchased units, net spend, recognized revenue and
profit. Freeze a shared old-context snapshot, common cutoff, requested model and
effort, same backend, six query items/six open items/12 total provider items,
600 seconds, and observable cost/token caps before dispatch. Unknown usage cannot
satisfy a numeric cap. Run each arm once; no rerun until A wins.

A actually uses the plan/routing/acquisition path; B uses competent ordinary
search and source opening. Both need actual linked search/open traces. Cache
benefit requires actual cache-attempt receipts, rather than availability of a
cache library. Do not preload the same source packet. Use a current bounded
capture window or an authenticated replay corpus; never backdate today's body
from an old heading. Search metadata as well as opened text is screened before
worker exposure.

Pool both arms' candidate economic units under neutral IDs for independent
source-grounded review. Canonical identity includes entity/product, metric and
its definition, period/cohort, unit/currency, epistemic status and value/condition.
Keep original lineage and source version separately. Rewording/sentence splitting,
IR/newsroom mirrors and syndicated text remain the same unit. Units already in
the frozen baseline are not new. One contractual asset meter is not evidence of
paid expansion or recognized revenue; missing links remain explicit gaps.

Compare supported-unit precision with judged denominator, unique new supported
units, bounded reference/facet coverage, redundancy, unjudged counts, distinct
original lineages and verified time coverage/lag. Unknown first availability
leaves detection lag unknown. Unjudged items in either pooled arm prevent a
comparative improvement claim. Warm-cache efficiency and injected-fault recovery
are separate cohorts; neither substitutes for cold acquisition richness.

The reusable supplement is
[`acquisition-contract.json`](../../tuning/evals/information_fetch/acquisition-contract.json).
The small [`acquisition.py`](../../tuning/evals/information_fetch/acquisition.py)
grader rejects missing search/open/cache evidence, future exposure, unreviewed
pooled units and incompatible controls. Use it through the existing sealed
contract's host `finish` path. This is not installed universal middleware or an
authentication of arbitrary handwritten receipts. Trusted capture, neutral review
packet construction and closure selection remain host responsibilities.

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m unittest \
  tuning.evals.information_fetch.test_acquisition -v
```

These are synthetic gate checks, not a newly executed acquisition comparison,
label-accuracy test or proof of a live web route. Jev labeling work is paused.

## Primary research informing the replacement

TREC's [Novelty guidelines](https://trec.nist.gov/data/t13_novelty/novelty04.guidelines.html)
separate relevance from information not already supplied by earlier material.
The [original alpha-nDCG paper](https://cormack.uwaterloo.ca/novelty.pdf) discounts
repeated coverage of the same nuggets. This supports a semantic economic-unit
inventory and redundancy penalty, rather than counting articles or paraphrases.
Alpha-nDCG is a possible secondary ranking metric; it is not yet implemented here.

Pool the two arms' eligible results, hide arm identities during source-grounded
review, and keep unjudged items unknown. Resulting coverage is relative to this
adjudicated pool, not absolute Web recall. [NIST's measures documentation](https://trec.nist.gov/pubs/trec20/appendices/measures.pdf)
explains incomplete relevance judgments. [TREC temporal summarization](https://trec.nist.gov/pubs/trec24/papers/Overview-TS.pdf)
provides a useful precedent for useful, new and timely updates. A newer article
about an unchanged event does not automatically resolve a newer information need.

[Freshness and relevance research](https://www.microsoft.com/en-us/research/publication/learning-to-rank-for-freshness-and-relevance/)
further supports question-dependent freshness. Keep publication, revision,
first authenticated availability and acquisition time separate. Detection lag
remains unknown when first availability is not established.

Atomic support/citation checks complement novelty checks: [FActScore](https://aclanthology.org/2023.emnlp-main.741.pdf)
measures atomic factual precision, while [ALCE](https://aclanthology.org/2023.emnlp-main.398/)
separates answer and citation quality. Neither establishes economic scope or
incremental acquisition coverage. Calibrate model judges against reviewed examples
and retain order-swapped results; the [LLM-as-a-Judge study](https://arxiv.org/abs/2306.05685)
documents judge bias concerns. These references motivate the design; they did not
test this implementation. Delegated fresh native search and primary-source opening
succeeded; this does not repair the root session's native transport circuit.

The new `information_fetch/acquisition.py` gate is a structural host-side adapter
around the existing sealed ledger. Its synthetic tests do not authenticate host
identity, calibrate semantic reviewers or constitute a newly executed acquisition
A/B. A real baseline-vs-addons search/open comparison remains pending the
planner-to-search dispatch boundary and frozen pooled-review workload.
