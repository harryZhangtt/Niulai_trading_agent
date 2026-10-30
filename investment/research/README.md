# Investment requirements and source coverage

This maintained investment adapter separates **what evidence is needed** from
**how it is acquired**. It composes with the preserved Niulai research validators;
it does not replace the financial model, review, valuation or entry-policy gates.

| Boundary | Owner and contract |
| --- | --- |
| `requirements.py`, `profiles/` | Investment question → immutable requirements snapshot and coordinator-held hash |
| `routing.py` | Snapshot → helpful provider capabilities; no network or snapshot edits |
| `shared/research_sources/` | Public query/identifier → actual source artifacts and typed receipts |
| `coverage.py` | Snapshot + actual passages + economic bindings + review → scoped coverage receipt or error |
| `pipeline.py` | Coverage gate + existing Niulai finalization/completion validators |

## Requirements snapshot

The coordinator freezes the material claim/question roster **before retrieval**.
The snapshot binds subject, cutoff, profile bytes/version, evidence families,
minimum access, allowed source hosts and questions. Its expected SHA travels in
the job/coordinator envelope, separately from worker output. Artifacts are immutable
content-addressed files; edits fail hash checks. Retrieval cannot lower a requirement
because a preferred source is unavailable. Scope amendments require a new reviewed
snapshot; do not silently re-pin after inspecting unfavorable evidence.

Profiles are data, not one agent/server per ticker. The first implemented technical
profile covers accelerated-compute claims with an **NVDA issuer override**. It asks
for first-party technical evidence, technical research, comparative evidence and
business realization. Other issuer overrides must be explicitly added and tested;
using NVIDIA hosts for AMD is rejected. `business-economics` is a small alternative
for nontechnical questions, with no arbitrary arXiv quota. Full NVDA records cannot
use that weaker profile. Required industry/technology claim IDs in the existing
record must be present in the frozen roster. The reviewer must still detect omitted
or misclassified material questions; the code cannot infer a complete economic thesis.

`examples/nvda-question.json` is a public one-question example, not a complete
NVDA research roster or an investment conclusion. Set the actual cutoff and all
material questions for each run. Do not copy its date into a new live run blindly.

## Run the separated path

Use the [research-source environment](../../shared/research_sources/README.md).
From the workspace root:

```sh
umask 077
mkdir -p .niulai-state/reports/investment-research/example
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m investment.research freeze \
  --request investment/research/examples/nvda-question.json \
  --out "$PWD/.niulai-state/reports/investment-research/example" > .niulai-state/reports/investment-research/example/contract.json
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m investment.research routes \
  --request .niulai-state/reports/investment-research/example/contract.json
```

Routing lists candidate capabilities, not successful queries or satisfied needs.
Use web search for broad discovery/contrary evidence, OpenAlex for structured
literature discovery, and versioned arXiv/document fetches for actual reading.
Only request information relevant to the material question. Reuse unchanged dated
artifacts within the declared validity boundary; do not refetch every source for
every question or treat cached material as current without checking its version.

## Execution checks

The coverage packet binds every requirement to fetched receipt references, actual
text offsets/passages, declared upstream lineage, applicability limits and an
economic link (`changed`, `unchanged` or `bounded`) to a real model JSON pointer.
A justified reviewed no-change result is valid; finding a paper must not force a
forecast change. The review is performed independently and hashes the exact packet.
It covers source meaning, workload/method applicability, lineage and economic transfer.

`coverage.validate` checks the coordinator pin, required roster, source family,
document access, revision availability/cutoff, raw and text hashes, exact passages,
lineage conflicts, model pointers, reviewer identity and review freshness/coverage.
When a real Niulai record is supplied it also checks the source passage is used by
the actual claim, the source snapshot is the fetched artifact, and the model artifact
is referenced by that record's model. Unknown availability cannot be backdated;
unversioned current docs use first-observed time. Metadata cannot satisfy a document
requirement. Failed/partial evidence remains a gap instead of a favorable default.

Both maintained entry points enforce this **in code**:

- `pipeline.finalize(item, out, contract=..., packet=...)` validates before calling
  preserved Niulai finalization, then binds the receipt to the completed record.
- `pipeline.complete(item, run_id, contract=...)` rereads and revalidates the
  pinned evidence before calling preserved Niulai completion. A valid old record
  without the new source contract is rejected.

The CLI exposes `assess`, `finalize`, and `complete`; inspect `__main__.py` for
their small JSON request shapes. `finalize` takes `{item, contract, packet}`;
`complete` takes `{item, run_id, contract}`. Preserve existing original receipts
and independent-review artifacts expected by the Niulai dependency.

This is enforcement in the maintained local entry points. It does not modify old
cloud tasks, make direct legacy-script invocation impossible, authenticate arbitrary
handwritten receipts or prove that a declared reviewer told the truth. Workspace
instructions route new work through these entry points. Strong adversarial isolation
would require a separately controlled coordinator/runner, beyond this local pilot.

## Verification and allowed claims

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m unittest discover -s investment/research/tests -v
```

Tests include a real composition with existing synthetic Niulai finalization and
completion fixtures, rather than mocking those gates. Atomic negative cases cover
rewritten pins, metadata-only evidence, fabricated passages, future revisions,
omitted coverage, repeated vendor evidence, missing model linkage and stale/self
review. The live pilot fetched real sources and proved metadata is blocked; it did
not fabricate a real NVDA model or reviewer approval to claim a completed analysis.
This verifies mechanics and scoped tool usefulness, not improved investment alpha.

Major runtime acceptance additionally uses `acceptance.py` through a future
one-time scheduled Codex session under the existing workspace policy. Its trusted
completion adapter independently rereads fresh source artifacts, the unchanged
requirements pin, metadata rejection, MCP identity/cleanup and regression outputs.
The supervisor records the actual slot/session and synchronizes the result to the
validated owner under the existing notification contract. This scoped test does
not create or approve an actual NVDA investment thesis. Until both execution and
email verification pass, the runtime integration remains unaccepted.

On 2026-10-30, the corrected v3 scheduled source test passed independent business
postconditions and its owner summary email was read back and verified. The two
prior failed attempts remain recorded: entry/state-boundary mismatch, then Node
missing from the scheduler PATH. The accepted fix uses explicit workspace entry,
the existing approved private output root and a hash-verified toolchain reference.
No global PATH or permissions were expanded. This accepts the tested source path
and gate mechanics, not a completed investment thesis or universal source quality.
Private acceptance records are in `.job-runtime/acceptance/`.
