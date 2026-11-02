# Real conversation persistence probe

`protocol.json` is frozen before model execution. `run.py` executes that sequence
through the installed Codex app-server, using the workspace's existing private
auth home under the shared nonblocking `runtime.lock`. It does not copy auth,
modify host configuration, schedule work, send email or run business senders.

Run from the workspace root:

```sh
python3 -B ui/portable/runtime_verification/run.py --record baseline-v1
```

The record is immutable and must be new for each attempt. Raw RPC traces stay in
`.job-runtime/acceptance/harry-ui-persistence-20261102/`; public summaries and
synthetic artifacts stay in `ui/runtime/harry-ui-persistence-20261102/`. The
profile is exactly the configured `default` model/effort, bounded to 120 seconds
per model turn. There is no retry or fallback. Successful tool events, returned
guide content and independent artifact hashes determine results.

Use `--preflight` for schema/discovery only (no model), `--variant fresh-v1` for
the frozen fresh wording, and `--stage baseline|candidate|scheduled` for receipt
labels. The harness itself never claims that a manual run is scheduled evidence.
The parent scheduler must record its actual future slot/session and verify the
business postcondition and email receipt under the workspace acceptance contract.

`--protocol candidate --stage candidate` runs the ten-task v2 roster in an
independent nested Git repository with the per-thread `project_doc_max_bytes=0`
setting. This prevents the parent workspace's UI policies from reinforcing the
portable skill. `--protocol independent` is the two-task activation/compaction
baseline control. Neither changes global configuration. `--resume-record` is an
explicit recovery option; the preserved baseline suffix uses it after a grader
defect and never repeats already completed task effects.

`run(args, cancel_event=event)` allows a scheduler to cancel. Waits check the event
at most a second apart, new RPC sends stop before starting a turn, and `finally`
terminates only the invocation's process group. Each record preserves exact
loaded harness/protocol bytes and process start/exit/cleanup information.

The original baseline `passed` field requires exact expected-expert conformance.
Prospective v2 cases declare relevant `allowed_experts`; layout/accessibility
overlap permits either focused layout or Impeccable hardening, with exact preferred
selection reported separately. The additional `persistence_passed` field checks
actual resolver use, an actually loaded guide selected by that resolver, and an
artifact effect. A strict baseline route mismatch can therefore fail conformance
while still showing that conversation routing survived.
Read commands must name the installed bundle path and return guide content;
identical text from canonical workspace experts is recorded separately.

V2 also requires a successful native-thread `session.py restore` before each
unnamed enabled UI turn's resolver. The harness independently reads the target
receipt, checks its thread/project scope, fingerprint and private file mode, and
retains a hashed state snapshot after each task. Disable must survive a real
compaction with identical tombstone bytes. The final fresh-thread control uses
the same project: its receipt must remain absent and the original thread's
enabled receipt must remain unchanged. Backend work makes no session helper call.

Prospective `--protocol candidate-v3` retains the same ten task prompts and every
enabled/fresh/state-scope check. In known-disabled context it permits no Harry
helper call; if a helper is used, it must successfully restore `DISABLED`. The
private disabled tombstone must remain byte-identical. The separate
`disabled_receipt_consulted` diagnostic is true only for an actual successful
disabled restore, never for the harness's independent receipt read or a model
claim. The original v2 strict failed result is preserved and is not regraded.

This is a narrow runtime conformance check. It does not estimate general
reliability or compare design quality/token efficiency. Earlier attempts remain
evidence even after a defect is fixed.
