# Upstream skill adaptation validation — 2026-10-30

## Acceptance and scope

Acceptance was defined before verification: all five existing routes must resolve
to substantive local upstream-backed implementations; source commits and licenses
must be retained; relevant supporting resources must work locally; concrete
domain mismatches must be removed from active procedures, with reasons recorded.
Protected investment data, holdouts and the Niulai snapshot were not used.

This is an implementation/compatibility check. It is not a benchmark establishing
that these adaptations improve agent decisions or investment outcomes.

## Executed checks

- **37 tests passed** on Python 3.9.6 using the standard library: 31 adapted
  upstream hypothesis-generation tests, plus six tests for the extracted
  Planning with Files phase-format validator. The upstream hypothesis tools
  declare Python 3.11+; this successful local run is compatibility evidence for
  the tested cases, not a promise about all older Python environments.
- The upstream test adaptation changes only resource paths and the shared
  `skill_contract` CLI-help harness. All seven public CLIs are tested directly
  with `--help`; no uninstalled upstream test package is assumed.
- Tested behaviors include duplicate/malformed input rejection, invalid causal
  records, rival predictions that fail to discriminate, measurement gaps,
  falsification controls, evidence-ledger consistency, scaffold provenance,
  unsafe input/output paths and static checks against external calls.
- Plan validation accepts a structurally valid pending plan without calling it
  complete; rejects absent/duplicate phase statuses and missing explicit paths;
  leaves input unchanged and does not execute commands written inside Markdown.
- All five entrypoints passed the installed Skill Creator's `quick_validate.py`.
  Its PyYAML 6.0.2 dependency was installed only in ignored
  `mentor/runtime/validation-env/`; the mentor skills do not require it at runtime.
- The bundle verifier checked five skill entrypoints, 62 imported-file hashes,
  full commit pins, license declarations and local Markdown reference targets.

Reproduce the executable checks from the workspace root:

```bash
mkdir -p mentor/runtime/test-tmp
TMPDIR="$PWD/mentor/runtime/test-tmp" PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s mentor/tests -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 mentor/tests/verify_skill_bundle.py
```

## Author walkthrough of development cases

The existing ten scenarios in `scenarios.md` were reviewed against the adapted
workflows. This is an author review of instructions, not independent model execution.

| Decision case | Applied route and reviewed behavior |
| --- | --- |
| Five deliverables followed by a simplicity constraint | Supervisor preserves accepted deliverables and reconciles artifacts; simplicity changes implementation choices. |
| User explicitly cancels deliverables | Required local context accepts the scope change instead of enforcing the old plan. |
| Broken native search with working browser fallback | Recovery isolates the failed boundary; successful fallback is not called native recovery. |
| Required data genuinely inaccessible | Recovery identifies evidence and alternatives, continues independent work, and reports the precise dependency. |
| Long task with new validated artifacts | Supervisor records progress and continues within budget; time alone is not a loop. |
| Identical permanent error on repeated attempts | Debugging requires a changed hypothesis or new evidence, not a numerical retry quota. |
| Proposed retrieval prompt change | Experiment workflow specifies rivals, measurements, controls and the acceptance rule before results; a project-specific worked design is linked. |
| Best of twenty variants on reused tests | Evidence context records all attempts, treats reused tests as development and requires independent confirmation. |
| Grader rewards persistent activity | Evaluation separates outcome/coverage/source support from cost; judge guide requires evidence and mapped pairwise identities. |
| Completion claimed with missing artifact | Supervisor's completion gate requires actual artifacts; the plan-format validator explicitly does not prove completion. |

## Pruning verification and limits

The active skill tree was searched for removed provider dependencies, paid-diagram
commands, hook registration, global plugin paths, fixed retry-escalation rules and
universal evaluation sample-size/threshold defaults. These procedures were removed,
not merely overridden with a disclaimer. The detailed decision record is
`../upstream/ADAPTATIONS.md`.

General scientific teaching examples remain where their methods transfer. An
example's source domain alone is not grounds to remove randomization, causal
reasoning, negative controls, multiplicity or replication. Original upstream
repositories are ignored review material, not installed or auto-loaded plugins.

No independent with/without-skill behavioral comparison was run. The next step
for a claim of effectiveness is a fixed, appropriately sized comparison on fresh
development tasks, followed by independent validation; it must not reuse these
visible review scenarios as a purported blind holdout.
