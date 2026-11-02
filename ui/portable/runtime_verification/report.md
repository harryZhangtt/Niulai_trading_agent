# Native conversation persistence verification

This update addresses the user's report that one `$harry-ui-skill-set` invocation
did not reliably cause later UI work to use the bundle. The earlier two-turn
subagent check established only that short instruction-retention path. It was not
complete persistence evidence.

## Reproduced behavior

Real `codex app-server` threads used the configured `gpt-6.1-sol`/low profile and
actual native skill input on activation, ordinary unquoted requests afterward,
real history compaction, a different app-server PID resuming the same thread,
tool events and independently read artifacts. No later UI prompt named the
skill, resolver or helper. Shell effects were limited procedurally to synthetic
fixtures; no OS sandbox or general reliability claim is made.

The workspace-context baseline used the original installed manifest
`81fae3929fe8ad0df654625c63409f11be97051c9be0e34bda51b4520e02df8f`;
its exact manifest is retained in the immutable baseline receipts.
Ordinary follow-ups routed successfully, but after actual compaction and again
after app-server restart/resume it edited the UI with **zero bundle resolver
calls and zero bundled guide reads**. This is an observed persistence failure.

A separate baseline control excluded this workspace's reinforcing instructions
with its own Git root and per-thread `project_doc_max_bytes=0`. It retained bundle
use after compaction, although it chose a different relevant guide from the
strict preferred one and recovered from a wrong card path. That is a routing/
path-recovery mismatch, not persistence loss. The observations are inconsistent;
they do not establish that the original failed on every compaction.

The original implementation had explicit-only metadata and retained activation
only in conversation text. Official documentation describes implicit selection
by description and `allow_implicit_invocation`; it provides no documented sticky
selected-skill latch. See [skills](https://learn.chatgpt.com/docs/build-skills)
and [app-server](https://learn.chatgpt.com/docs/app-server).

## Repair and boundaries

The owned user-scope package now permits implicit discovery, while preserving
strict per-conversation opt-in. An uninitialized fresh thread does not activate
automatically. Explicit initialization writes a private, atomic target-local
receipt in `.ui-skill-runtime/harry-ui-sessions/`, keyed by native
`CODEX_THREAD_ID`, target and bundle fingerprint. That environment ID was observed
in actual tool execution to equal the native app-server thread ID; it is a tested
runtime capability rather than a documented cross-version API promise.
`CODEX_SESSION_ID` is not used: forks may share a session-tree root.

On enabled/uncertain UI work the wrapper must restore the current native-thread
receipt before calling the resolver, then read appropriate actual bundle guides.
After compaction it reloads needed guide bodies. Backend-only work makes no Harry
call. A known-disabled conversation stays quiet; if an implicit selection checks
uncertain state, `DISABLED` remains off. Explicit re-enable is required.
Unknown/corrupt/foreign state is preserved and fails visibly. Disabled tombstones
survive compaction and package updates; valid enabled state refreshes on an owned
package update. No shared global flag, global hook/config edit, active MCP,
credential copy or dependency installation is introduced.

The installed v3 manifest is
`407d03cdf6ca4cc7d166953370c31d435c1cf91bf8243cec3a754702cb02a0e4`.
Owned atomic directory exchange retained both previous exact payloads/receipts
inside workspace rollback stages. Publication and rollback preserve changed/user
files and hold uncertain exchanges for reconciliation.

## Actual tests and preserved versions

Manual candidate v2 ran ten real task turns in an independent Git root:

| Boundary | Observed result |
| --- | --- |
| Explicit activation, native identity and local artifact | Passed |
| Four unnamed enabled UI turns, including actual compaction and restart/resume | Restore ACTIVE before resolver, actual guide use and artifact effects passed |
| Backend diversion | No helper/resolver/guide calls; enabled state preserved |
| Explicit disable | Native disabled receipt and no active bundle use passed |
| Unnamed disabled UI after another real compaction | Scope and byte-identical tombstone held; no helper was called |
| Explicit re-enable | Passed |
| Fresh thread in same project | No opt-in inherited; own receipt absent and original enabled receipt unchanged |

V2's strict literal contract **failed 9/10** because it demanded a restore helper
even when the mode was already disabled. Independent review confirmed the
literal failure and also confirmed that no user-goal/safety violation was
observed in that disabled turn. Its failure, raw traces and score remain unchanged.

Prospective v3 was declared before fresh execution. It aligns source instructions
and outcome criteria: all active restoration, native scope/privacy, actual
resolver/guide work, off-state integrity and fresh-thread controls remain
mandatory; known-off helper use is optional. If attempted, it must successfully
restore DISABLED. `disabled_receipt_consulted` records actual helper evidence,
never the supervisor's own independent read or a model assertion.

V3 protocol SHA-256:
`37712ddb374b5bfc5dbcc40175a465ec1e4c0270c4e60327d83dbf96ae13e3c1`.
The prior v2 SHA/score and earlier harness defects are preserved. A null-output
handling bug and an overbroad guide-content matcher were repaired with tests;
canonical guide text is not counted as bundle use without the executed bundle
path. Completed effects were read back rather than replayed.

Local source checks passed: **44** package/session/upgrade checks, **44** runtime
trace/scheduler checks, **13** startup checks and official skill metadata
validation. Native state tests include concurrent independent threads, permissions,
FIFO/symlink/unknown data, scope separation and tombstones. Gate tests reject
forged receipt fields, missing/wrong helper order, private-state redirection and
scope inheritance.

The first future allocation, `confirm-v3-01`, was retired with **zero model
attempts** after the admission guard treated an enabled periodic recovery job
as permanently busy. It is preserved as **unverified**, not a skill failure or
a passing run. A new distinct allocation used a corrected admission guard
that preserves active-primary/daily-wake priority and the existing exclusive
auth lock; no production configuration is changed.

Fresh future-scheduled v3 confirmation **passed** in the distinct
`confirm-v3-02` allocation. The installed GUI launchd scheduler claimed its future
once slot exactly once; its native thread started **6.94 seconds** after the
05:40:35.961890 UTC due time and completed at **05:47:30.346903 UTC** on 2026-11-02.
The requested/observed model was `gpt-6.1-sol`, requested effort low, with no model
retry or fallback. Parent project policies were excluded by an independent Git
root and `project_doc_max_bytes=0`; later task prompts contained no router or
helper reminders.

All **10/10 actual task turns** and **13/13 cases** passed, including two completed
native compactions and new-PID resume of the same native thread. All four unnamed
enabled UI turns executed one successful ACTIVE restore before one bundle
resolver, with **zero reactivations**, actual relevant bundled guides and artifact
effects. Guides were returned again after compaction. Backend exclusion passed.
Explicit disable, a second compaction, unnamed disabled work and explicit
re-enable passed. The disabled task used no helper, so
`disabled_receipt_consulted=false`; its exact tombstone remained unchanged.
A fresh thread in the **same project** read the wrapper but did not activate,
resolve or load experts; its receipt remained absent and the original enabled
thread's receipt stayed unchanged.

The root and an independent reviewer replayed actual raw events and reopened
private native-thread/project/manifest-bound receipts, artifact hashes and the
scheduler database. Both app-server process groups exited 0 and are absent; the
unique temporary label unloaded itself and the primary labels remain registered.
The loaded harness/protocol, installed payload and source/profile/CLI fingerprints
matched the staged candidate exactly before and after execution. The prior v2
result and zero-attempt allocation remain separate immutable history.

Execution is **passed**; the configured-owner supervisor acceptance summary is
**verified** by exact Gmail raw readback of the recipient, subject and HTML.
This supervisor email is separate from the scheduled tool/receipt evidence. Automatic repository SessionStart execution remains separately
unverified; its message now announces resource readiness rather than asserting
durable opt-in without a receipt. This one bounded synthetic sequence establishes
the tested local Codex0.166.0 persistence path, not a statistical reliability
estimate, cross-version guarantee, comparative rendered-design improvement or
OS-level isolation.

## Evidence and reproduction

Source protocol, harness, raw-event grader and isolated scheduler are in this
directory. [The frontend runbook](../../../docs/deployment/frontend.md) documents
commands and runtime paths. Raw model/native traces and scheduler state are
private under `.job-runtime/acceptance/harry-ui-persistence-20261102/`; sanitized
results and synthetic artifacts are under
`ui/runtime/harry-ui-persistence-20261102/`. Baseline and v2 failures are immutable.
Successful command items, native IDs, independently validated private receipts,
actual compaction events, process cleanup and artifact hashes establish the
scoped results; a final assistant declaration does not.

Current serialized context proxies are **873** tokens for the whole installed
entrypoint, **541** for the intent card and **1,737** for the local startup
protocol payload (`tiktoken0.12.0/o200k_base`). Receipt restoration adds context
and tool work; the earlier classifier savings do not establish savings for this
persistence repair. Model-reported runtime usage is separate from these proxies
and from billed usage.

The successful scheduled sequence emitted **1,683,336 input tokens** (including
**1,542,784 cached input**) and **10,048 output tokens**, for **1,693,384 total**
in native cumulative counters across its two distinct new threads. The
independent diagnostic deduplicates resume of the same thread, rather than
summing repeated cumulative events. Three unchanged events were excluded from
delta accounting; all nonzero deltas matched their reported last counters.
Compaction accounting remains ambiguous because those events did not advance
the same cumulative counters. These figures describe this tool-heavy conformance
sequence, not billed cost, parent-session consumption, restore-only overhead or
a matched token-savings comparison. The portable card still loads experts
selectively; it does not make all implementation work cost541 tokens.
