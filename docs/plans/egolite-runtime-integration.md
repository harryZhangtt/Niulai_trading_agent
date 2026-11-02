# Unattended web access through registered actions

Decision record, 2026-11-01. Extends the configurable-pipeline plan. The target
registration below is proposed; the current catalog still contains only
acquire_document, read and compare_numeric. Do not interpret this plan as an
active browser tool, scheduler allocation or accepted production route.

## Entry points and responsibilities

Acceptance requires native skill activation in the scheduled session. Installed
Codex0.166.0 uses `/skills` → List skills → ego-browser, inserting the native
`$ego-browser` attachment. A direct CLI read is lower-layer connector evidence
and cannot pass this user criterion. The isolated native route now has three
future scheduled passes; see the deployment runbook and private acceptance receipt.

```text
common scheduler -> application-owned pipeline runner -> pinned skill transport
  -> native /skills selection -> skill-attached Codex turn -> approved request
  -> shared host web adapter -> installed EgoLite CLI/app
  -> immutable observation -> independent completion check -> replay/notification
```

Keep wake/model/retry ownership in shared/job_runtime. Keep pipeline phases and
required business outputs in investment/research. Keep routing, browser protocol,
limits and private observations in shared/web_access. Register the reviewed
capability in the existing shared/actions catalog; do not build another catalog
or hot-add an MCP server. The control UI selects a reviewed release, not a CLI
command, JavaScript snippet, auth home or arbitrary filesystem path.

The browser action does not wake Codex or a sleeping/offline Mac. Unattended use
still depends on the installed scheduler and a usable logged-in GUI/browser
session. A successful foreground read cannot establish either prerequisite.

## Smallest useful action contract

Proposed selector: `evidence.browser_read@1`. The agent supplies an approved source
handle (or a URL subsequently authorized by the host); the runner supplies the
run/action identity, pinned private browser config, resource scope, remaining
deadline and output directory. The model cannot choose those host values.

The host intersects the published action allowlist with source-origin/session
authorization, central ceilings and the phase's remaining budget. A mandatory
browser-read step is dispatched and its receipt checked by the state machine;
prompt wording and a model's final assertion cannot satisfy it. Optional source
discovery may be model-proposed, subject to the same checks. A denied proposal is
recorded without launching a browser. Missing required evidence blocks completion.

Successful output is a hash-bound browser observation reference. It remains a
rendered extract, with requested/observed URL, retrieval time, truncation and
cleanup state; it is not automatically a full document, independent source or
verified financial fact. The authoritative action receipt binds request,
arguments hash, release, outcome and observation. Replay exposes those bindings
and sanitized policy decisions, not raw page payloads or credentials.

Pin the action code/schema/environment, navigation script and installed helper;
record the actual browser build when observed. Publication binds exact action and
pipeline releases. Edits do not replace an in-flight run's pins. CLI/app upgrades
need new verification and matching scheduled acceptance.

## Session ownership, pressure and retry

Own one browser task space for a multi-read job, reuse its pages, and finish once
after successful completion. Retain an errored/user-controlled space and its
identity for reconciliation. Never mint a new space to evade a stop. The current
single-read probe finishes its space after that one bounded read; it is not yet
the multi-read lifecycle implementation.

Reuse existing common scheduler retry/resource admission for scheduled attempts.
The existing market-data QueryPortal already has bounded pending work, shared
retry quota, jitter, Retry-After and a circuit breaker, but is coupled to Node/MCP.
Do not claim direct browser reuse merely because the policies look similar, and
do not wrap the Python/browser adapter in a pretend MCP client. Extract its
transport-independent admission policy only when wiring the shared browser host;
retain compatibility tests for the existing consumer. A profile-scoped gate must
cover concurrent processes, not just threads or one stateless CLI invocation.

Browser navigation is a stateful external operation. Timeout, lost protocol or
unverified cleanup means unknown task state: hold, inspect the same task, then
reconcile. Authentication, permission/user control, policy denials, version drift
and malformed protocol are not automatic retries. Retry only a classified
transient failure known to precede dispatch, or an explicitly reconciled safe
continuation, within central attempt/time/quota ceilings. Never shorten a real
Retry-After or clear cookies to reduce reauthentication. Preserve normal sessions;
expiry still requires the user's normal login/verification.

## Ordered implementation and acceptance

1. Real CLI source read, independent source/hash/cleanup verification: observed.
2. SDK-channel, protocol/error, concurrent admission and atomic intent checks;
   bounded local/owned-page stress. Report fixture versus live coverage separately.
3. Coordinate catalog/schema/frozen-bundle changes with the runtime owner. Add the
   host-only resource/lifecycle interface and strict pipeline completion binding.
   Preserve existing historical releases; do not silently replace published bytes.
4. Run the sealed matched native/Ego reader cases, retaining all failures. Public
   cases do not accept signed-in sessions, iframes or general browser superiority.
5. Exercise the exact candidate in a real future scheduled Codex session. Verify
   slot/session/timing, source anchors, pins and cleanup independently, then send
   and exactly read back the configured owner's acceptance email. Preserve partial,
   failed and unknown outcomes. Follow runtime-acceptance.md; no foreground or
   unit-test result substitutes for this final gate.

The first useful slice requires no new service, database, frontend framework,
global Codex setting or production sender cutover. Source config stays disabled
until the intended route and acceptance evidence exist. See the component runbook
for setup, containment limits and recovery.

## User acceptance correction: native slash activation is mandatory

On 2026-11-02 the user explicitly required stable runtime slash-command
activation. This supersedes treating direct CLI execution as sufficient for this
acceptance. Historical CLI/source/load results remain adapter evidence only.

The installed Codex CLI0.166.0 rejects `/ego` as unrecognized. Its supported route
was observed in an actual interactive session: `/skills` → List skills → select
ego-browser → native `$ego-browser` attachment. A slash string in a codex exec
prompt, manually opening SKILL.md, or a direct browser CLI call cannot satisfy
that native activation gate. A documented typed skill API is a different route;
do not silently substitute it for this requested literal slash test.

Candidate shared/job_runtime/skill_tui.py drives this native selector in a real
PTY with pinned CLI/skill bytes, the existing private auth-cache lock, approved
workspace-write roots and the current automatic-review policy. It has no CLI-only
fallback. Shell/model turns are not sent until the selector has inserted the
expected skill. A durable submission fence precedes Enter. Pre-dispatch auth
contention is retryable under the existing engine's bounded policy; unsupported
commands, drift and wrong selection fail. Interrupted/unknown submitted turns
remain held, including any uncertain browser tasks. No auth cache is cloned and
no hook is automatically trusted. This transport is candidate code, not an active
replacement for the installed recurring executor.

Acceptance requires future scheduler claims, actual native selector/skill input
and Codex session/turn evidence, intended browser operation, independent source
URL/hash/content/cleanup checks, candidate equality, declared timing, absence of
duplicate operations, and exact-readback owner notification. Repeated successful
future slots plus exception/retry cases are required for the tested stability
claim; none establish perpetual availability. TUI idle text alone is not a
backend turn/completed receipt or business acceptance.

The isolated native-slash slice subsequently passed three future scheduled
public-guide probes, with independent native history, full-guide hash, source
and cleanup verification. See the deployment runbook for timing and the preserved
failed predecessor. This does not activate the proposed shared/actions browser
registration or replace production job allocation.
