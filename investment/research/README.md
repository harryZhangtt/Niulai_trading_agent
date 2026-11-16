# Investment requirements and source coverage

## Project-local investment review entrypoint

The canonical instruction wrapper is
[`investment-review`](../skills/investment-review/SKILL.md). Codex discovers it
through the project-only link `.agents/skills/investment-review`; from this
checkout, invoke it with a request such as:

```text
$investment-review NVDA, review through today and reuse existing research and sources
```

It routes the current agent through the preserved investment research adapter,
bundled AI Berkshire/growth-aware policies, existing source tools and data
cross-checks, independent review, and applicable maintained completion gates.
For full company work, the route is `freeze` / `routes`, actual evidence/model
work, `assess`, `pipeline.finalize`, then `pipeline.complete`. No extra executor,
MCP server, package, global skill or hook is installed. Other instruments and
explicitly narrow requests retain their applicable profile and completion scope.

The investment component owns the wrapper. Before its discovery link is created
it is a **staged host-impacting** instruction candidate; the link makes it
**active session-impacting** for project skill selection. The affected scope is
research sessions in this checkout and their authorized private artifacts.
It cannot block prompt submission, diagnosis, notifications or recovery and adds
no automatic external publication, email, trade, schedule or background process.
Existing external-effect ownership and authorization continue to apply.

For deployment on another device, deploy the canonical file with this repository
and create the relative project discovery link only after validating the source:

```sh
mkdir -p .agents/skills
ln -s ../../investment/skills/investment-review .agents/skills/investment-review
```

An existing destination must first be reconciled; never replace another skill.
For rollback, verify that the destination is still the owned symlink resolving
to `investment/skills/investment-review`, then unlink only that link. Preserve the
canonical source and all research artifacts. Recheck native skill discovery
after installation/removal; a file's presence alone does not prove discovery.
The wrapper is not added to the separate maintained Claude dollar-alias catalog.

Reuse `.research-sources/.venv` and the existing source-cache paths below. Research
checkpoints, reports and evidence remain in new private directories under
`.niulai-state/reports/investment-research/`, written by the existing artifact
helpers. Do not modify historical quarantined artifacts or introduce a new
dependency on user-global packages. A resumed run rechecks input hashes and
invalidates affected downstream results.

The entrypoint's validation/discovery evidence is recorded separately from actual
research completion. Skill loading cannot establish that sources were obtained,
AI Berkshire methods were executed, independent review passed, or a report was
published. Full research and future-scheduled runtime/email acceptance remain
unverified until their own actual evidence exists; earlier source-path acceptance
below does not accept this new wrapper.

Verification on 2026-11-15: the Skill Creator validator passed, all eight local
references resolved, and a fresh isolated native Codex app-server discovered the
installed canonical entrypoint enabled from the repository root, `investment/`
and `investment/research/`. Disposable probes also verified ordinary session
creation with an unrelated malformed skill present, owned-link removal/restoration
and process cleanup. The first probe incorrectly expected native discovery to
reject malformed description YAML; the diagnostic and corrected probe preserve
that observation. The separate strict validator rejected the malformed fixture.
Native discovery therefore does not replace installation preflight. A read-only
independent instruction review found no material defect. These checks used no
model turn, actual investment review or business delivery. Private probe and
owned-installation receipts remain under ignored `investment/runtime/`.

The unregistered runtime-information-catalog candidate is described in
[the catalog and labeling design](../../docs/plans/runtime-information-catalog.md).
It compiles question plans from current evidence/capability context and keeps
document/claim label contracts separate. It does not replace the full-company
requirements or completion gates below. Its strict historical context screening
does not authenticate archived source versions or implement the future replay
search/open broker. The deployment runbook records component/preflight results
and the remaining retrieval A/B integration work.

The scoped evidence/action pilot has a separate
[runtime runbook](../../docs/deployment/investment-research.md). It exercises
original-source extraction, versioned action integrity, ordered phases, scoped
use checks and snapshot CRUD. It does not replace the full-research gate below.

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
  .research-sources/.venv/bin/python -c \
  'import sys; from investment.research.pipeline import publish_contract_pointer; publish_contract_pointer(sys.argv[1], sys.argv[2:])' \
  "$PWD/.niulai-state/reports/investment-research/example/contract.json" \
  "$PWD/.research-sources/.venv/bin/python" -m investment.research freeze \
  --request investment/research/examples/nvda-question.json \
  --out "$PWD/.niulai-state/reports/investment-research/example"
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m investment.research routes \
  --request .niulai-state/reports/investment-research/example/contract.json
```

The outer helper first buffers producer stdout in an owner-private `0600` file
under the approved destination directory. It requires a zero producer exit, parses
one strict JSON value, validates the complete requirements contract and referenced
snapshot, and only then atomically switches `contract.json`. Producer, validation,
or pre-replace failures preserve the previous pointer. A post-publication directory
fsync failure is an unknown outcome that must be reconciled from the attached
readback evidence; do not blindly rerun it.

SQLite primary-mode coverage below applies to newly created databases only. The
existing `Store` implementation owns reopen/chmod and journal/WAL policy; this
artifact hardening does not claim to preserve the mode of a pre-existing database
or govern transient SQLite sidecars.

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
