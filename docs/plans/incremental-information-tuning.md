# Tuning acquisition for incremental information

The measured problem is a mismatch between a fixed-packet reasoning test and an
acquisition claim, plus unexercised source/cache routes. The native portal also
initially discarded useful search metadata. Fix execution and context loss before
adding retrieval models. Existing rule/knowledge labels remain provisional; Jev
is paused by the user.

## Smallest useful sequence

1. Same-query/captured-response control checks exact answer-bearing passage,
entity, period, heading and table-context preservation. Record raw/normalized/
issued hashes, truncation and missing fields. A parse failure is different from
a transport failure or an irrelevant source.
2. Current-window acquisition A/B freezes the common questions, old inventory,
model/backend, allowed access and6 search+6 open logical-item budget. A executes
catalog/gap-driven searches and the actual cache wrapper; B conducts competent
ordinary searches with the same capture/safety logging. Separate cold caches.
Unused retries or reader fallbacks establish no advantage.
3. Pool issued document passages under neutral IDs. One common extractor and
independent reviewer identify supported canonical economic units, old-baseline
matches, material refinements, counterevidence, independent confirmation and
redundancy. This measures candidate information richness without confounding the
collection agent's writing or ability to notice a fact already present.
4. Report per-question novel units and bounded pooled-reference/facet coverage,
precision, lineage redundancy, supported period coverage, timing and unknowns.
Publication, observation and first authenticated availability remain distinct.
No authenticated first-availability time means no measured detection lag.
5. Diagnose the first failed transition, fix one evidenced cause, and run a new
sealed development version. Keep failures, ties and regressions. Reserve different
queries/source families or a later window for confirmation; one correlated NOW
workload cannot establish general superiority or investment alpha.

## Primary-method rationale

[Anthropic contextual retrieval](https://www.anthropic.com/research/contextual-retrieval)
adds source context to chunks before lexical/embedding indexing and evaluates
reranking. It motivates testing context preservation; it does not justify a new
vector database without measured misses.

[MMR](https://www.cs.cmu.edu/afs/.cs.cmu.edu/Web/People/jgc/publication/MMR_DiversityBased_Reranking_SIGIR_1998.pdf)
balances query relevance against redundancy, and [BEIR](https://arxiv.org/abs/2104.08663v4)
shows that retrieval methods need heterogeneous evaluation. Test a small passage
selection variant only after the actual eligible pool contains competing useful
passages. Independent corroboration and contradictions must not be removed by
blind similarity filtering.

[Self-Ask](https://aclanthology.org/2023.findings-emnlp.378/),
[Adaptive-RAG](https://aclanthology.org/2024.naacl-long.389/) and
[CRAG](https://arxiv.org/abs/2401.15884v3) motivate explicit missing-information
subquestions and bounded corrective retrieval. Their methods/results do not
establish a gain for this pipeline. Begin with declared unmet-facet rules rather
than training another router.

[Lost in the Middle](https://aclanthology.org/2024.tacl-1.9/) supports testing
context placement/length on the actual model. [TREC Novelty](https://trec.nist.gov/data/t13_novelty/novelty04.guidelines.html)
and [alpha-nDCG](https://cormack.uwaterloo.ca/novelty.pdf) motivate novelty relative
to accumulated context and repeated-nugget discounts. We use economic-unit
coverage as a practical proxy, not Shannon bits or final decision value.

## Minimal traces

Requirement -> planned query -> actual dispatched route -> raw result -> parsed
metadata -> eligible opened version -> issued passage -> reviewed nugget.
Every edge carries execution/arm/requirement/operation IDs, version/hash/time,
cache/recovery reason and budget. Classify not-planned, not-executed, access,
normalization, truncation, temporal rejection, redundant, unsupported and issued-
but-unused separately. Existing immutable receipts are the local source of truth;
optional remote trace export must not block execution.

[OpenTelemetry GenAI](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md),
[OpenInference](https://arize-ai.github.io/openinference/spec/semantic_conventions.html)
and [LangSmith custom traces](https://docs.langchain.com/langsmith/annotate-code)
provide conventions and parent/child span patterns. No active LangSmith exporter
was established in the maintained local source. Its [RAG tutorial](https://docs.langchain.com/langsmith/evaluate-rag-tutorial)
usefully separates evaluation stages, while its broad demo relevance grader is
too permissive for our answer-bearing economic-novelty criterion.

EgoLite remains a scoped reader candidate. The foreground reader comparison
passed native3/4 and Ego1/4 with clipping/node-omission limits. A later single
ServiceNow configuration-page comparison returned loading/cookie content through
EgoLite while native targeted reading recovered mechanisms. These limited tests
do not establish general reader superiority. Connector or scheduled startup
acceptance is a separate claim from useful source extraction. Prefer the
appropriate observed reader and trace an actual fallback when used.

## Runtime feedback with a small effort budget

Treat a retrieval need as a question and required evidence fields, not a fixed
list of websites. After a read, the agent records one bounded assessment:

```text
requirement ID -> operation/source version -> supported candidate or missing link
              -> outcome reason -> next permitted action or stop
```

The agent judges meaning and economic scope. Scripts enforce identity, source
hashes, cutoff, literal quotations, retained requirements and resource limits.
A topic label or successful read does not complete a requirement. Current
catalog compilation and HostWeb receipts support these mechanical boundaries;
the gap assessment/selection is a cooperative agent procedure, not an automatic
semantic controller or universal source-quality score.

| Observed result | Cheap next action within the original budget |
| --- | --- |
| Navigation, excerpt too early, or missing section | Inspect heading/line locator, then one targeted same-URL read if justified |
| Failed or unparseable payload | Retain failure; use a different supported document/representation, without pretending the first read succeeded |
| Already-known statement or syndicated copy | Preserve any corroboration role; spend the next query on an unmet field |
| Anonymous allegation or conditional opinion | Retain as a lead; seek original terms, a named operator, or contrary evidence |
| Unsupported economic link | Query that link explicitly; do not infer paid use from usage or revenue from ACV |
| Useful new mechanism | Save the scoped passage and remaining limitations; inspect the next unresolved question |
| No adequate route, unknown outcome, deadline or cap | Save an explicit gap and resume condition; stop identical attempts |

Keep three kinds of value separate: new/refined information, independently
originated corroboration, and unresolved leads. For measured marginal novelty,
compare supported canonical units with both the original baseline and units
already acquired in that run. Repeated wording earns no new-unit credit.
Corroboration may still be useful and must not be silently deleted by deduplication.

Azure's [agentic retrieve response](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-how-to-retrieve)
provides a useful implementation precedent: record actual subquery activity and
partial-source failure separately from the plan. Its
[overview](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
also documents added latency/cost. We adopt the observable feedback principle,
without adding that platform or assuming that more planning improves quality.

## Current evidence and next comparison

The [first real NOW pair](now-acquisition-ab-20261102.md) produced A18/B15 new
supported answer-bearing units; excluding explicitly anonymous material in an
exploratory sensitivity gives A14/B15. Detection lag is unknown. A robust overall
quality or freshness gain is therefore not established.

A new sealed development pair gives ordinary `find`/targeted-open to both arms.
A additionally compiles the existing catalog and reserves query/read budget for
observed gaps; B remains a competent ordinary searcher. Both have identical
6-search/8-read/14-provider-item caps, baseline, questions, backend and cutoff.
Results must retain source-role strata, unresolved twelve evidence needs,
failures and costs. The changed budget makes its absolute counts inappropriate
as a direct improvement estimate over the first pair; compare A versus B within
each pair. The second NOW test is tuning evidence, not an untouched confirmation.

The six-unit baseline is deliberately narrow. Before a database-wide enrichment
claim, freeze the relevant existing catalog and stored research notes as prior
context, with their original roles and unknown dates intact. A note can establish
that our research already considered a mechanism without authenticating its
underlying factual assertion. Current-context reuse and strict historical source
eligibility are different checks. Measure novelty against that broader baseline
and accumulated run context; otherwise old research can be recounted as a new
discovery. Do not silently promote catalog metadata into a read source body.
