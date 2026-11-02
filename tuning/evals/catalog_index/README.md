# Raw catalog index: isolated development verification

The supplied offline prototype was reviewed, hash-checked and rerun before using
its responsibility split for this component. The implementation reuses existing
artifact/observation/snapshot storage and adds a small read-only catalog adapter.
It does not import the prototype as a runtime dependency or copy its DCF machinery.

The real input is the preserved local research database, frozen through SQLite's
read-only backup interface. It contains 65 artifact entries, 71 section entries,
253 active evidence notes and 95 latest active assessment notes. Asset associations
normalize these into 713 indexed records across 81 entity labels. The security
registry has 74 securities; seven additional labels, including the unmapped bucket,
are exposed as registry gaps. No alias reconciliation was guessed.

| Verified path | Observed result |
| --- | --- |
| Frozen XLS/XLSX rebuild | Feature/label files matched exactly; 15 published rounded statistics and 256 same-provider alignment checks reproduced |
| Supplied forecast replay | 124 included cases, 4 retained purges; reported numeric metrics reproduced |
| Supplied helper/evaluator checks | 8 functional tests and 8 rejected injected faults |
| New source/investment suites | 71 + 79 checks passed; 10 focused new checks are included in these totals |
| Sealed host conformance, corrected v1.0.1 | 10/10 critical postconditions passed |
| Initial normalization/index | 713 associations, 5.46 seconds |
| Entity queries and candidate snapshots | 81 entity labels, exact expected record sets, 2.62 seconds |
| Identical corpus replay | 713 reused records, 1.26 seconds, no new revisions |
| Durable-index replay stress | 20,000 repeated puts/readbacks, all reused, 34.12 seconds |
| Four-process overlap | 128 requests for 32 records: exactly 32 creations, 96 reuses, one revision per record |
| Revision race | Stale snapshot refused; earlier snapshot/history remained readable |
| Resource observation | Entire workload 43.87 seconds, parent peak RSS about 103.5 MiB; concurrent child memory excluded |
| Source/archive side effects | Original database hash unchanged; no jobs, broker, model, network provider or schedules invoked by the index workload |

These are associated catalog/note records, not 713 independent sources or recovered
report bodies. Dates unknown in the catalog remain unknown. Original URLs and past
full-text-read flags do not authenticate report content on this host. Source
support, information-value gain and full agent-runtime readiness remain untested.
The 20k test reuses 713 real records; it does not ingest 20k unique PDFs. The
prototype's CPU-only metadata timing is a different workload and excludes I/O.

All package-manifest hashes matched. The original prototype execution receipt has
one later-file hash difference for its source-integration review; this is retained
as a qualification. The first index run passed its original ten criteria but
exposed a route-accounting defect outside those criteria: concurrent request
replay sometimes said `created`. Overall acceptance was withheld. Version 1.0.1
fixed that defect and strengthened the host check before a fresh run. Both attempts
and source pins remain in the private ledger. An initial broader test invocation
also failed because a legacy fixture used system TMPDIR; the documented local
TMPDIR corrected the invocation without modifying that fixture.

Study identity: `raw-index-integration-20261031`. Private record:
`.niulai-state/reports/research-sources/runtime/raw-index-integration-20261031/record.json`.
It binds the source/copy/roster hashes, prototype evidence, original and corrected
contracts/results, raw workload outputs, query snapshots and registry gaps.
Shared metrics describe one correlated run and must not be summed across cases.
This is development conformance, with no blinded holdout or alpha claim.

Run the isolated public import with the workspace-local command in
[the runbook](../../../docs/deployment/investment-research.md#isolated-raw-catalog-indexing-candidate).
Run focused checks using:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m unittest \
  shared.research_sources.tests.test_indexing investment.research.tests.test_catalog -v
```

The output is bound to a frozen corpus; a changed/deleted roster needs a new output
directory. Per-record CAS remains available for scoped correction workflows.
Current bounds include 1 MiB normalized records, 8 MiB immutable artifacts, a
1,000-candidate scan per entity and at most 128 returned candidates. Truncation
and deferral remain explicit. Larger-scale pagination and batch coalescing should
be driven by actual load, not inferred from this pilot.

No production action, scheduler or MCP configuration was activated. The next
integration is an explicitly versioned candidate query/snapshot action and a
small source-bound information-contribution test; actual runtime activation still
requires future scheduled Codex execution and verified owner-email acceptance.
