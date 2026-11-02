# Temporary development campaign

The separate [six-hour review/capture controller](review-campaign.md) serves
parent-staged acquisition A/B evidence reviews. It does not resume this old
implementation campaign or inherit its A–F steps or acceptance evidence.

The optional `shared.job_runtime.campaign` controller reuses the durable Engine,
model/authentication lifecycle helpers and explicit workspace-local Python. It
does not edit the installed service, its allocations or business profiles.

Create from the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 .job-runtime/.venv/bin/python -m shared.job_runtime.campaign create --name evidence-mvp-YYYYMMDD
```

Use the returned absolute directory as `--state` for `install`, `status`,
`activate`, `stop` and `tick`. `install` bootstraps one temporary user launchd
label from its workspace-resident plist, with no login link. It wakes every 60
seconds to inspect a finite roster of 48 one-time opportunities, spaced 15
minutes apart. The first opportunity is due 60 seconds after creation. There is
no model call on ordinary idle checks. No automatic authentication or consent
flow, provider install, sandbox bypass or MCP activation is supplied.

The initial state is `probe_pending`. Its first actual scheduled Codex session
must create and execute a tiny challenge module in the isolated work copy.
The controller reruns an independent assertion. Inspect that receipt and the
actual thread/slot/attempt/timing before `activate`. `probe_passed` alone proves
only this development path. Workspace acceptance also requires the configured
owner's verified result notification; it does not prove the investment MVP.

The public-source copy includes current tracked/unignored source from selected
component directories, including uncommitted changes. It excludes original
private runtime/auth state. Six mentor discovery links are reconstructed, and
the canonical mentor initializer is explicitly invoked for each slice. This is
manual context loading, not a claim that the child app automatically trusted or
fired SessionStart. Shell writes are restricted by the CLI workspace-write mode
to the disposable work area and its allowed temporary paths. Apps/MCP/web search
are disabled; public adapter network access is enabled. The existing single
authentication-home lock is shared and never copied or bypassed.

Hard ceilings are twelve hours from creation, 16 model starts, 600 seconds per
slice and 7,200 cumulative model seconds. The observed-token guard is 500,000
input+output tokens across slices; it acts between calls and one call may exceed
the remainder. Unknown usage stops the campaign. These are ceilings, not targets
or billing guarantees. Maximum output uses the existing model-profile limit.

One campaign lock serializes tick processes. A running/unknown primary job,
approaching daily wake or occupied authentication cache makes development yield.
This is cooperative priority on one host, not zero shared-resource interference.
Clock rollback stops the run. Sleep/reboot never extends the absolute expiry;
missed slots expire rather than catch up. The host must remain available; the
campaign does not install a boot/login service or promise multi-day uptime.

Workers implement one package at a time in their copy, run fixed external
regression checks, and save `docs/campaign-progress.json`. Only content changes
with passing checks count as progress; prose, timestamps and heartbeats do not.
Two no-progress slices, two matching failures, an observed source-hash cycle,
protected-code modification, explicit blocker, unknown outcome or exhausted
budget stop further model calls. A completed package is still subject to review;
the last package ends as `ready_for_review` and never merges/deploys itself.

The worker cannot edit the controller, external checks or limits. Production
code remains unchanged until a parent reviews the isolated diff. The worker's
allowed source edits are investment/, shared/actions/, shared/research_sources/
and docs/. Shared scheduler integration and business acceptance stay with the
parent after review. Local test subprocesses are time-bounded and their exit
codes/log hashes are recorded independently of model assertions.

`stop --state ABSOLUTE_STATE_DIR` writes a cancellation request without waiting
for the worker lock. Active model execution checks it and terminates its process
group. A check already running may take up to its bounded timeout to finish.
At the next idle tick, terminal campaigns unload only their own launchd label.
If a coordinator died, an unfinished intent is `unknown`; it is not replayed.
An orphan model is terminated only after matching its recorded process birth
and work-copy identity. Failure to establish ownership is not authority to kill
an unrelated process. Keep all receipts and reconcile unknown state manually.

State layout:

- `.job-runtime/campaigns/<id>/config.json`, `state.json`, `campaign.plist`:
  private configuration, counters and temporary launchd specification.
- `worktree/`: disposable public-source copy; no automatic writeback.
- `engine/schedule.sqlite`: separate slots/attempts; primary DB untouched.
- `attempts/<id>/`: actual mentor result, bounded CLI events, process identity,
  independent check logs and receipt.

Verification uses virtual time for the full 12-hour guard and real processes
for lock/cancellation behavior, followed by a future-triggered live probe and
independent readback. These prove mechanisms and the tested moment; twelve-hour
endurance remains pending until actual elapsed observations exist. Preserve
failed runs and unknown outcomes. Any material controller change invalidates its
pin and requires a new reviewed campaign/probe.

The 2026-10-31 guard repair excludes documentation/generated files from effective
implementation progress and requires step-specific changed code/tests plus
nonempty structural artifacts. In particular, checkpoint-only edits cannot move
A–F forward even when the old test suites pass. Eleven controller checks cover
this mechanism, including execute-level two-no-progress stop and refusal of a
third dispatch. These are development checks, not full 12-hour endurance. The
old campaign remains stopped/unloaded; a new probe may validate the repaired
controller without activating implementation or modifying the main checkout.
