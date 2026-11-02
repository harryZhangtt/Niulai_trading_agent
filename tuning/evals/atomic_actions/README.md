# Atomic versioned-action development cases

These four questions test the existing acquisition, passage-reading, and numeric
comparison actions. The outcome under evaluation is a supported answer with
correct limits. This is a development, unblinded round; the authors inspected
the sources and expected facts. Separating worker inputs from the oracle does
not establish OS isolation, unseen-case generalization, or investment alpha.

`cases.json` contains public questions, source targets, dimensions, budgets, and
a neutral output schema. `oracle.json` contains the host's expected facts,
relationships, limitations, source locators, and failure criteria. It contains no
private runtime paths. The schema constrains structure without fixing the
answer. Worker submissions do not declare their own pass status, usage, action
records, or authoritative comparison results.

| Case | Primary distinction |
| --- | --- |
| `nvda_eps_basis_q1fy25` | GAAP, adjusted measurement, and the share denominator |
| `nvda_historical_vs_latest_period` | Historical results, outlook, retrieval date, and an unresolved latest-period request |
| `flashattention3_h100_scope` | Exact revision, mechanisms, benchmark controls, and unsupported extrapolation |
| `nvda_revenue_units_periods` | Raw units, different periods, normalized agreement, precision, and common upstream |

The cases are correlated: three use one issuer release and one uses a manuscript
already inspected during development. Four cases provide targeted coverage of
failure mechanisms, not a statistical reliability estimate. OpenAlex discovery
and broader source coverage remain separate from this action slice.

Before dispatch, the host reviews and freezes the complete roster, separate
expected objects, source bindings, packet inputs, grader source closure,
candidate releases, and budgets using the existing
[`evidence_runtime/contracts.py`](../evidence_runtime/contracts.py). Every attempt
is registered before execution. The worker receives public questions and source
or comparison references, without the oracle, acceptance labels, or grader code.
All four cases remain critical. A failed or unknown case cannot be dropped or
relabelled after results. Any material case or grader revision starts a new
contract version; no passing-output selection or silent rerun is permitted.

Bind source references and exact passage spans in the private run artifacts.
Oracle offsets describe the inspected normalized text identified by its digest;
they are not portable offsets for a newly fetched page. Re-resolve short anchors
and surrounding section context against the actual capture before sealing.
Ambiguous anchors or changed article facts require an explicit preparation gap,
not fabricated provenance. For the paper, provide public section-location hints
resolved by the host so the small read budget tests reasoning rather than a
linear scan of a long document. The worker still performs the registered reads.

The host prepares three comparison packets for the revenue case from the actual
capture: original units, distinct periods, and normalized same-period values.
Keep the supplied metadata and source lineage intact. Derivations, normalization
rules, freshness policy, and rounding tolerance are declared before model work.
Unknown metadata remains unknown; the comparator can legitimately return
`unverified`. Do not fill a missing period start or source timestamp merely to
obtain a favorable status. If a complete packet requires a calendar derivation,
record that derivation separately from the document's reported dates.

At most six actions and seven model turns are allowed per case, with twelve
fresh HTTP requests and twelve minutes across the complete round. Reuse captured
source bytes where the declared execution arm allows reuse, and label those
calls as imports or cache reads. One direct arXiv acquisition uses both identity
and HTML requests. Do not retry a permanent failure unchanged. The actual
execution path owns timeouts, usage, candidate checks, and final acceptance.

Grade source identity, period, units, basis, citation support, numerical behavior,
and stated limitations separately. Structural validity precedes semantic review.
Verify quoted spans against bytes actually read by the action, and cross-check
numeric claims against the host-bound observations and calculation receipts.
Do not require the oracle's prose or a fixed action order. A plausible answer
with invented citations, wrong periods, erased adjustment basis, unsupported
current conclusions, or an incompatible comparison presented as agreement
fails its corresponding critical criterion. Missing provider evidence can leave
the answer correctly incomplete; it is not permission to invent a fact.

Record every run's complete coverage, gaps, tokens and cost where observed,
unknown usage explicitly, latency, calls, and critical failures. Optional tracing
or display warnings must not discard an otherwise usable source result. Missing
evidence for an acceptance assertion remains unverified rather than being
reported as observed business failure. The orchestrator owns the scheduled
Codex acceptance, independent verification, and configured-recipient email;
these fixtures alone do not establish that gate or claim a live evaluation ran.

Host implementation: `workload.py` reuses the existing action/phase/model APIs;
`grade.py` independently opens receipts and requires an answer/source/oracle-bound
review with the complete frozen critical-criteria roster. `acceptance.py` seals
before a future once slot, records every case, then grades once after review.
Blocked cases cannot disappear: their semantic grade fails and metrics remain
unknown. For budget maxima only, missing observed counts use the existing
configured upper bounds, explicitly distinguished from observations. There is
no new engine/control/UI service.

The adjacent-period contrast retains the reported value/quarter end but leaves
its unavailable start unknown. The oracle permits `unverified` for that specific
incomplete packet; complete metadata must meet its stricter comparison status.
No fiscal start is invented to force a successful result. Equivalent fiscal-year
notation and decimal precision are accepted; wrong periods or accounting labels
still fail. These policies are fixed before the actual model answers.

Round1.0.0's grouped-EPS representation false-negative and round1.0.1's inaccurate
model-proposed citation subrange are preserved as failed evaluations. Contract
1.0.2 uses claims' `passage_locator`, copied from actual read outputs; source-ref
plus issued locator resolves an exact observed passage. Model-created subranges
cannot pass the host boundary. The neutral question/answer content remains
unchanged and equivalent labels/periods are accepted. Source-grounded review is
still required for meaning, including a claim attached to the wrong issued read.
