# Frozen document/topic label accuracy

`grade.py` is a deterministic adapter around the existing sealed evaluation
contracts. It makes no provider/model call and generates no gold labels. Gold
must be independently prepared and frozen before either classifier arm runs.
This mechanism evaluates **document type and topic decisions**; it does not
establish source truth, passage support, epistemic-status accuracy or investment
alpha. Those require separately defined gold and gates.

An eight-case public-source run is development evidence. Source/chunk overlap is
reported through `source_group`; correlated chunks are not independent trials.
Confusion, macro-F1 and probability losses on eight cases do not prove broad
accuracy, calibration, statistical significance or superiority. A label remains
provisional unless a separately reviewed promotion rule is satisfied.

## Frozen input and output

Each sealed case input has exactly these fields:

```python
{
    'source_ref': source_receipt_ref,
    'chunk_ref': utf8_bytes_ref,
    'taxonomy_ref': frozen_taxonomy_ref,
    'source_group': 'one-original-source-version',
    'cutoff': '2026-11-01T15:59:29Z',
    'allowed_document_types': ['earnings_release', 'analyst_report'],
    'allowed_topics': ['financial.performance', 'business.model'],
}
```

The chunk must be an exact nonempty UTF-8 substring of the hash-checked source
text (maximum 24,000 bytes). Source raw/text, taxonomy and chunk references are
verified before dispatch and while grading. Both acquisition and availability
timestamps, plus declared modified/updated/version-availability bounds, must be at or before cutoff. Publication dates alone cannot admit
current text into a historical case. These checks are local integrity boundaries,
not authentication of historical timestamps or an OS sandbox.

Host-only expected data uses `document_types:[allowed answers]`,
`topic_sets:[[one allowed exact set], ...]`, `abstention_allowed:bool`.
For unique gold, `document_type:string` and `topics:[...]` are equivalent forms.
The contract's case-level `critical` flag is frozen separately. Ambiguous gold
must be explicit before classification; it cannot be expanded after seeing an
answer. Accuracy allows any predeclared answer; probability metrics are unknown
when there is more than one gold target.

Normalize the classifier output without gold access. Missing, disabled or error
transport status fails the case with `LABEL_TRANSPORT_UNVERIFIED` and unknown
quality metrics, even when gold permits abstention:

```python
{
    'transport_status': 'ok', # required: ok, partial or abstained
    'source_sha256': source_ref['sha256'],
    'chunk_sha256': chunk_ref['sha256'],
    'taxonomy_sha256': taxonomy_ref['sha256'],
    'document_type': 'earnings_release',  # None means abstained
    'topics': ['financial.performance'], # explicit positive decisions
    'topic_abstentions': [],             # unknown, distinct from explicit no
    'document_probabilities': {'earnings_release': .8, 'analyst_report': .2},
    'topic_probabilities': {'financial.performance': .7, 'business.model': .7},
    'latency_ms': 12,                    # None if not observed
    'cost': None,
}
```

Enum probabilities must cover the exact frozen options and sum to one within
`shared.typed_judge.contracts.PROBABILITY_SUM_TOLERANCE` (currently `.001`).
Distributions are preserved without renormalization; a classified document must
be an argmax within the client contract's `1e-6` comparison tolerance. Topic
probabilities are independent binary `P(true)` values; they must **not** be
normalized across topics. Missing probability fields stay unknown. Jev enum
confidence is not accuracy. Topic abstentions are excluded from selective risk
and reduce coverage; full abstention cannot report perfect topic F1. Probabilistic
Brier/log-loss can still be evaluated from valid probabilities under abstention.
Log losses clip probabilities at `1e-15` to keep ledger metrics finite.

## Sealing and execution

Build the ordinary evidence-runtime spec with `metrics=grade.METRICS`, full case
roster/criticality, identical per-arm numeric budgets, split and blindness label.
Use this API in order:

1. `seal(spec_path, candidate_fingerprints, directory, extra_grader_paths=...)`.
2. `worker_packet(contract_ref)` returns only input references and budgets.
3. `begin(..., arm, budget, fingerprint)` **before** any worker dispatch.
4. Save each normalized output as an immutable artifact.
5. `finish(..., submissions=[{id,output_ref},...], usage=...)` exactly once.
6. `summarize(contract_ref,result_ref)` reports the scoped metrics.

The default closure pins this evaluator, the sealed ledger, artifact and timestamp
helpers, and the shared typed-judge contract containing the probability tolerance.
Include the actual classifier/adaptor scripts and configuration/prompt
sources in `extra_grader_paths` or the candidate fingerprints. Root/source and
chunk bytes, taxonomy/option roster and host-only gold are frozen separately.
Worker packets omit gold only at packet level; their filesystem remains shared.
Do not claim OS isolation or unseen holdouts.

`finish` preserves failed records for missing/duplicate cases, changed gold/code,
source mismatch, exceeded budget or invalid labels/probabilities. No hard case may
be dropped. Existing failure/result/finish-intent records cannot be overwritten
or blindly replayed. `record_unknown(claim_ref, directory, reason)` archives an
unknown worker outcome; the claim remains nonreplayable. Grading may later
reconcile already existing outputs without issuing another worker call. A new
model dispatch needs a separately registered attempt, retaining the original.

Use only observed usage dimensions as numeric budget counters. Unknown cost or
tokens must not be replaced by zero to pass a budget. Latency/cost metrics retain
known/unknown denominators. There is no weighted quality composite or automatic
model promotion. The per-case deterministic gate requires exact allowed labels
(or explicitly allowed complete abstention); critical failures remain visible.

The summary reports selective document accuracy separately from completion and
end-to-end accuracy over **all required cases**. Failures, missing cases and
abstentions cannot disappear from the latter denominator. Coverage uses all
required document/topic decisions; unavailable transport is separate from a
semantic abstention. Known failed-call latency/cost stays observed. Unknown cost
does not become zero.

Topic micro precision/recall/F1 remains conditional on known binary decisions.
The separate `emitted_tag_*` metrics measure positive tag precision and capture
across every required case with one unique topic gold set, counting transport
failures and abstained gold-positive topics as missed positives. Predeclared
ambiguous topic sets are excluded from those metrics and probability losses;
their allowed-set match rate is reported separately across all required cases.
Macro-F1 includes observed gold/predicted classes with a defined F1 denominator
and reports that class count. Ambiguous document gold is excluded from
confusion/loss calculations and reported separately. No metric is a promotion
rule.

## Review-gated development screen

`screen.prepare(manifest_path, review_path, directory)` materializes eight exact
chunks only after a separate coordinator review receipt names the exact manifest
SHA-256. The receipt must identify its review as
`coordinator_ai_development_review_not_human_gold`; it is not independent human
annotation. The manifest retains source references, exact Unicode offsets and
chunk hashes, predeclared ambiguities, cutoff, rationale and common budgets.
Preparation checks temporal admission and source integrity, preserves raw
taxonomy-file bytes, and returns an ordinary spec reference. It neither seals
the contract nor dispatches a worker.

After all implementation/configuration bytes settle, the host seals the returned
spec with `extra_grader_paths=screen.CLASSIFIER_SOURCES` plus other actual runtime
dependencies, then registers **both** attempts before any classification. Each
arm receives only `worker_packet` inputs, never `expected_ref` or rationales.
Shared filesystems mean this is packet separation, not a protected holdout.

`normalize_rules` uses the unchanged existing URL/origin rules. An unknown
document and every topic with no positive hint are **abstentions**, not explicit
negative predictions. Its probabilities and monetary cost stay unknown.
`normalize_labeler_report` preserves Jev's exact source/chunk/taxonomy bindings
and distributions. A blocked, disabled, failed or unknown call is an unavailable
transport outcome rather than a semantic abstention; recorded elapsed time is
retained when present.

The existing rule method uses URL/origin metadata; the current Jev consumer sends
only the passage. Both arms are bound to identical source/chunk/taxonomy/cutoff
inputs and common numeric budgets, but use different features. This compares
workflow policies and cannot isolate intrinsic model superiority. The reviewed
roster has eight distinct source versions, four from ServiceNow, and reuses the
NOW smoke source. Those observations are correlated development evidence, not
eight independent trials or unseen validation. The provisional `.60` probability
and `.10` margin policy is fixed for this round, without a calibration claim.

`run_screen.py` is a small host runner over these APIs. Its `prepare` command
seals the approved spec and fixed Jev configuration (model `jev-1.14.0`, 45-second
attempt, 60-second total deadline, zero retries), pins the runner and shared
runtime sources, registers **both** arms, and saves gold-free worker packets.
Each arm and case gets a durable intent before execution. A repeated arm fails
before dispatch. Candidate cases have isolated caches and engine scope
`label-accuracy-dev-v1`. Any unavailable candidate outcome stops subsequent live
dispatch; remaining cases retain explicit `not_dispatched` outputs.

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m tuning.evals.label_accuracy.run_screen prepare \
  --preparation /absolute/path/to/immutable-preparation.json --directory /absolute/private/state/run-v1
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m tuning.evals.label_accuracy.run_screen run \
  --run /absolute/path/to/returned-run.json --arm baseline
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m tuning.evals.label_accuracy.run_screen run \
  --run /absolute/path/to/returned-run.json --arm candidate --allow-live
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m tuning.evals.label_accuracy.run_screen verify \
  --run /absolute/path/to/returned-run.json
```

Only the candidate `run --allow-live` command authorizes network dispatch. There
is no credential-value, endpoint or retry override. `model_calls` counts observed
transport dispatch attempts, including unknown provider outcomes; it is not a
billed-completion count. An unexpected exception without a receipt leaves that
counter unknown and the ledger's usage gate fails. Monetary cost stays unknown;
provider-reported usage is retained separately.

`verify` makes no call or artifact write. It rechecks the contract/source closure,
both registered claims, packet and case bindings, retained provider model/limits,
typed output, deterministic grades and summaries. CLI verification requires
HTTPS receipts; synthetic transport is available only to direct test APIs.
`integrity_status=verified` means retained evidence is internally consistent.
Semantic failures and unavailable cases remain visible and do not need to pass
for integrity verification; neither status is automatic runtime acceptance.

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m unittest \
  tuning.evals.label_accuracy.test_grade tuning.evals.label_accuracy.test_screen \
  tuning.evals.label_accuracy.test_run_screen -v
```

These synthetic tests exercise the evaluator's integrity boundaries. They do not
measure Jev or another label classifier. Actual public-source scoring, model
fingerprints, retained failed/unknown attempts and future scheduled acceptance
remain separate host-owned work.
