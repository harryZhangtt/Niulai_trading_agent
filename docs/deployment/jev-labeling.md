# Optional Jev source labeling

This is an opt-in development integration with TypeSafe's pinned `jev-1.14.0`.
It annotates exact captured public passages. It does not establish source truth,
investment usefulness, calibrated confidence or approval for default labeling.
No automatic classifier, global model override or active market MCP is installed.

The preserved [paused handoff](../handoffs/jev-labeling-20261101.md) records the
first POST's unknown outcome. A separately registered source E2E subsequently
returned the pinned model, valid twelve-question output and usage in about1.1s;
its live-disabled repeat used cache without another call. The
[eight-case screen](../../tuning/evals/label_accuracy/report.md) retained two
valid responses, a45s unknown timeout and five unstarted cases; its artifact
integrity passed, but coverage/semantic gates did not. Future-triggered runtime
acceptance **failed**: the first slot lacked the workspace import path; two later
slots were fenced at startup without creating a Codex session or Jev output.
The matching prelaunch path indicates auth-cache contention, and a subsequent
snapshot observed another Python/Codex pair holding that lock. The corrected
command's explicit project-local `PYTHONPATH` imports were independently checked
without network, but that does not accept scheduled execution. All three Jev
acceptance allocations are now disabled and their failures retained. Coordinate
exclusive use of the existing auth cache before registering another future slot;
do not clear locks, copy rotating credentials or bypass the retry fence.
Email synchronization is recorded separately in the private acceptance record.
Do not relabel the original timeout as a pass or a negative classification.

## Boundaries and dependencies

- `shared/typed_judge/`: typed questions, closed response validation, bounded
  subprocess HTTPS, normalized immutable cache and sanitized execution receipts.
- `investment/research/source_labeler.py`: source/cutoff/chunk admission,
  one document Choice plus eleven independent topic Noul questions and optional
  source-bound provisional sidecars.
- `investment/research/jev_acceptance.py`: once-only public-source exercise and
  independently checked source/model/cache postconditions.
- `tuning/evals/label_accuracy/`: sealed public development cases, gold-free
  worker packets, retained arm attempts and deterministic grading.
- `mentor/runtime/`: ignored supervision/recovery notes, not experiment logic.

Use the existing project-local `.research-sources/.venv` created with the
[research-source requirements](../../shared/research_sources/requirements.txt).
No package is installed globally or added for this integration. The generic
scheduler environment does not need `jsonschema`: the stdlib-only completion
adapter delegates read-only domain validation to that research environment.
Both environments must be provisioned before scheduling on another device.

## Credentials and private paths

Provision `.job-runtime/credentials/jev.api-key` locally through a hidden prompt
or an approved secret manager. Never put its value in prompts, command arguments,
source, fixtures, environment-wide configuration or receipts. The existing file
is not a portable deployment artifact. The worker requires a regular,
non-symlink, current-user-owned file with mode0600 or0400. Keep the parent private
and ignored. Do not overwrite or copy a rotating credential during setup.

Private output roots are `.niulai-state/reports/research-sources/` for source,
cache and eval artifacts, and `.job-runtime/acceptance/` for scheduled evidence.
Prepare `.job-runtime/tmp` before live calls; it is the isolated HTTP child's
temporary-directory setting. Host verification uses
`.research-sources/jev-validator-tmp`. All paths stay inside this workspace.
No proxy, shell profile or global Codex setting is changed.

## Deadlines, retry ownership and recovery

Shared defaults remain live off,5s per attempt,10s total and zero retries.
Explicit limits permit at most60s per attempt and120s total. This development
exercise separately registers45s per attempt,60s total, retries0, a256KiB request
cap and64KiB response cap. These are bounded development settings motivated by
the observed slow host; they are not an adaptive latency SLA.

Only the root coordinator authorizes live dispatch. The HTTPS child uses an
environment allowlist, a pinned endpoint and no redirects. A wall timeout kills
and reaps the child. A timeout is `JUDGE_TIMEOUT_UNKNOWN_OUTCOME`: the provider
may have received or billed the call. Do not automatically replay it. Retain the
attempt and reconcile before authorizing a distinct attempt. Auth, validation,
model mismatch and malformed output are not transient negatives. The shared
client can explicitly retry429/529 once within its total deadline, but this
screen and source acceptance deliberately configure zero retries.

A positive cache contains validated normalized outputs, not raw provider bodies
or keys. Identity binds model, endpoint, engine scope, question schema/policy,
request and transport kind. Corruption fails closed; preserve it for diagnosis
rather than automatically fetching again. Existing attempt directories cannot be
replayed. The source E2E's second invocation disables live access, so a missing
cache becomes a failed postcondition rather than another POST.

## Reproduction

Run focused conformance checks from the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m unittest \
  shared.typed_judge.tests.test_client \
  investment.research.tests.test_source_labeler \
  investment.research.tests.test_label_sidecars \
  investment.research.tests.test_jev_acceptance \
  tuning.evals.label_accuracy.test_grade \
  tuning.evals.label_accuracy.test_screen \
  tuning.evals.label_accuracy.test_run_screen -q
```

The E2E CLI requires an immutable reviewed manifest reference and a new attempt
ID/output directory. Only an explicit `--allow-live` opts in. Its read-only
`--verify-report-ref` mode accepts no execution/live arguments. See the
[module interface](../../investment/research/jev_acceptance.py) and
[evaluation runbook](../../tuning/evals/label_accuracy/README.md). Review exact
public chunks and provider retention terms before registering a new live run;
default zero-data-retention is not established. Do not upload private reports.

Freeze gold, source/chunk/taxonomy/cutoff, code, provisional thresholds and equal
arm budgets before dispatch. Register both arms before either runs. Rule hints
use metadata; Jev uses passages, so this is a workflow development comparison,
not a same-information causal model experiment. Unemitted rule topics abstain.
Preserve failures, unknown usage/cost and unstarted cases separately from semantic
abstention. The runner stops further live dispatch after a transport failure.
Read-only verification distinguishes artifact integrity from semantic case gates.

Thresholds .60 probability/.10 margin are an unvalidated development policy.
Choice confidence is a distribution statistic, not independent P(correct).
Noul questions are independent probabilities, not one topic softmax. Eight
reviewed cases include correlated source families and an already used smoke
passage; they are not a held-out accuracy or calibration benchmark.

## Scheduled acceptance and rollback

Use a fresh future `once` job under the existing business profile, model/auth
ownership and approval mode. Bind a new manifest to the exact candidate source
fingerprint. The scheduled Codex session must perform a fresh HTTPS source call
and cache-only repeat in its own new attempt directory. The completion adapter
independently rereads typed receipts, source/chunk/schema/sidecar bindings and
cache identity. Preserve every attempted slot and do not edit an existing job's
schedule to obtain a retry. An old foreground smoke is not scheduled acceptance.
The scheduler deliberately starts in an isolated private working directory.
Use the absolute research interpreter and an explicit `PYTHONPATH` pointing to
the workspace in each command; do not assume inherited shell state or make the
repository writable to solve an import error. Verify imports without live calls
from that isolated directory before registering a repaired future slot.

Record the real thread/slot/attempt/timing and sync success or failure to the
configured owner with an exactly verified `[CODEX]` email according to the
[runtime acceptance contract](runtime-acceptance.md). A supervisor notification
does not claim the scheduled session sent email. Keep production email jobs and
their deduplication fences unchanged. Rollback disables only the Jev acceptance
allocation and leaves live opt-in off; preserve receipts and unknown outcomes.
