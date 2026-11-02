# Native search and EgoLite candidate

Status on 2026-11-01: project-local router, bounded candidate connector and sealed
development evaluation are implemented. EgoLite remains disabled in source config.
After scoped user authorization, vendor app0.6.2.5 was installed in the user's
Applications directory; its CLI and automatic skill/profile files are present.
Strict codesign and Gatekeeper checks pass. CLI guide v2.2.0 was loaded.
The user completed onboarding. A subsequent real CLI read of the vendor Codex
guide passed independent snapshot/hash and temporary-task cleanup checks, without
a slash command. Initial onboarding/protocol failures remain preserved. The
installed macOS SDK writes console.log results to stderr and adds a blank line;
the bounded connector accepts that framing only through its strict nonce-bound
single-record parser. Source config remains disabled; a four-case live paired round now exists, with failures described below.
Future scheduled acceptance is unverified. OS defaults/global Codex/shell settings
were not changed and Chrome data was not imported.

## Source and operation ownership

- `shared/web_access/policy.py`: host-owned session routing, native transport
  circuit, exact initial/final origin checks and finite read/deadline ceilings.
- `shared/web_access/egolite.py`, `ego_read.js`: executable-hash pin; authored v2
  navigation/full-page snapshot only; private intent/observation refs; no automatic
  retry, generic JS input, clicks, form submission, credential export or installer.
- `tuning/evals/browser_cooperation/`: fixed cases, existing sealed-contract gate,
  independent reader/anchor conformance and blocked preflight.
- `docs/web-search-routing.md`: incumbent live research workflow. New candidate
  code does not intercept host tools or alter its default fallback.

Native web search discovers issuer/original and contrary sources. Native open
reads ordinary pages cheaply. Escalate an insufficient/interactive or explicitly
authorized signed-in source to EgoLite after readiness is verified. Keep PDF
handling on the existing native/PDF route. Chrome/ChatGPT Work remain explicit
host-tool alternatives. A transport error opens the host session's native circuit;
no repeated native calls or hidden fallback-as-primary success. A per-page access
gap does not by itself establish native transport failure.

`Session` state is in-process and host-owned. The standalone `plan` command is a
diagnostic, not persisted circuit state across separate commands. A production
host integration must keep one Session for the real task and independently
record native outcomes. Native search cannot be implemented by a fake HTTP
request or a successful browser handshake.

## Portable local commands

No new Python package, global dependency or active MCP server is needed. Use the
existing project interpreter. All wrapper/evaluation artifacts go under the
existing private `.research-sources/` root, excluded from version control.

```sh
python3 -B -m shared.web_access doctor
python3 -B -m shared.web_access plan --operation discover
python3 -B -m shared.web_access plan --url https://arxiv.org/abs/2106.09685
python3 -B -m shared.web_access plan --url https://arxiv.org/abs/2106.09685 --interactive
python3 -B -m unittest discover -s shared/web_access/tests -v
python3 -B -m unittest discover -s tuning/evals/browser_cooperation/tests -v
python3 -B -m tuning.evals.browser_cooperation.experiment \
  --out .research-sources/web-access/evaluations/round-003
```

`doctor` checks discovery/pins without launching the browser; a passed CLI pin is
only ready for an explicit probe. The evaluation command freezes four cases,
graders and candidate fingerprints before work and records preflight. It does
not execute a live A/B trial. Never infer zero approvals/reauth/cost from missing
telemetry, and never count an unavailable browser as a completed comparison.

## Concrete external setup requiring a workspace exception

The default workspace scope permits project-local changes. Root AGENTS requires:
“All task-created or modified files must remain within this workspace unless the
user explicitly authorizes an exception.” EgoLite's standard app installation,
profile and onboarding are outside that boundary. External installation requires the explicit scoped exception recorded below.

The user authorized this scoped exception on 2026-11-01 and requested sequential
execution: normal setup and real source E2E first, then atomic/error and bounded
throughput checks. Authorization does not remove the general workspace boundary
or permit the excluded changes below. Installation/readiness remain separately
verified outcomes.

Installed evidence: private install-receipt.json and external setup authorization
under mentor/runtime/browser-cooperation-20261101/. Vendor Developer ID is
CITRO LABS PTE. LIMITED/JGQLC6YQYJ. The installed signed/notarized build initially
contained FinderInfo metadata rejected by strict verification. Only that metadata
was removed following Apple QA1940; no quarantine attribute was removed and no
signed code was rewritten. Both strict verification and Gatekeeper then passed.
DMG SHA256: 3f4ae2584300736897af8987bc5eb17b1ebea2cb6fcee16eed1f90f95616317e.

The current normal user installation uses `~/Applications/ego lite.app`, the
vendor profile under `~/Library/Application Support/Citro Labs/ego lite` and
the vendor launcher `~/.local/bin/ego-browser`. Use the pinned resolved helper
path rather than editing shell PATH. Private egolite-installed.json enables only
explicit probes, not a new workspace/default browsing route. Reinstall and
reverify on another device; do not copy the profile/cache or private config.

1. Install the vendor's signed macOS app through normal OS verification in
   `/Applications` or `~/Applications`; do not strip quarantine or bypass Gatekeeper.
2. Permit EgoLite's own profile/cache/runtime data, launcher and its documented
   automatic per-agent skill registration outside this checkout. Record actual
   changed locations during setup; normal app behavior is not workspace-isolated.
   Do not modify global Codex settings, shell profiles or system network settings.
3. Complete first-run onboarding. Start with a research profile and public sites;
   do not import the full Chrome profile/passwords or sign into financial accounts
   as a side effect. Additional signed-in research needs explicit site/session
   authorization. Disable optional task/page-content improvement collection.
4. Resolve the actual `ego-browser` executable, inspect the version-matching
   `ego-browser skill` guide, and verify the installed API/runtime. Retain version,
   hash and sanitized probe evidence; new vendor versions require new pins.
5. Copy candidate.json to a private workspace config, set enabled true, exact
   executable path/hash and approved research profile ID. Do not alter PATH in
   shell profiles; use the explicit path. Keep only task-relevant exact origins.
6. Probe one approved public page, verify content/URL/cleanup independently, then
   run the matched trial with a new sealed contract using the installed pins.
   A readiness string alone cannot accept source reading.

Vendor references inspected on 2026-11-01:
[installation](https://github.com/citrolabs/ego-lite/blob/main/skills/ego-browser/references/install.md),
[v2 API](https://github.com/citrolabs/ego-lite/blob/main/package/ego-browser/src/public-api-schema.ts),
[privacy policy](https://www.egolite.ai/privacy).
The checked API supports taskSpace, page.goto/url/snapshot and finish; the
candidate connector's first installed-app attempt was blocked on onboarding;
the later completed-onboarding read succeeded.
The installed v2.2.0 guide requires retaining an errored/user-controlled task for
reconciliation, so the authored script now calls finish only after successful
observation. Successful cleanup was independently observed after the real read. Broader
error/load and scheduled-runtime coverage remain distinct acceptance steps.

## Evidence and containment limits

Receipts contain requested/observed URL, config/script identities, retrieval time,
snapshot hash, truncation, cleanup and observed elapsed time. Observations are
`rendered_extract`; they are not auto-promoted to existing `document` receipts or
full-company coverage. References preserve source lineage; different readers of
the same issuer page are not independent sources. Raw content stays private;
CLI output contains refs/stable codes, not page bodies or raw provider errors.

The wrapper checks the initial allowed origin and the final origin before taking
a snapshot. This is not a redirect/subresource network firewall: browser navigation
can run site code and visit redirects before a final check. The external browser
retains its own permission/network/profile model. Do not claim an adversarial OS
sandbox or full protection of a general logged-in browser profile. The first
trial is public-only with a dedicated profile and no business writes.

Output growth is sampled and wall time bounded. Timeout/protocol/cleanup failures
return blocked with unknown task state and no automatic retry; reconcile the
named task space in the browser. If process-group signalling is denied, the
wrapper kills/reaps its own leader and retains cleanup-unverified diagnostics.
Killing a CLI does not prove the separately running browser stopped navigation.

## Evaluation, activation and rollback

Follow the [frozen comparison protocol](../../tuning/evals/browser_cooperation/README.md).
Compare paired source/anchor coverage, failure gaps, calls/time and only observed
approval/reauth events; preserve critical failures and all cases. First isolate
the reader on common discovered URLs; end-to-end routing is a separate round
with matched model/effort/questions/budgets. Unknown billing stays unknown.

No automatic adoption. Evidence must show the tested stratum's benefit without
critical coverage/safety loss. Public cases cannot establish signed-in/login or
iframe reliability. Broader claims require dedicated authorized/synthetic cases.
Activation also needs the real future scheduled Codex route and verified owner
notification under the runtime acceptance contract. Source/CLI/scheduler/model
changes invalidate matching acceptance until retested.

Rollback is to keep/restore the source candidate disabled and continue the
incumbent native/Work/Chrome route. Preserve observations and uncertain task
records; never clear browser cookies, revoke sessions or delete old receipts as
an automatic recovery. No OS default-browser change is necessary for this design.

## Unattended action integration

No slash command is needed for programmatic CLI use. The
[unattended integration plan](../plans/egolite-runtime-integration.md) separates
scheduler wakeup, application-owned pipeline enforcement, proposed action
registration and the shared browser adapter. The browser action is not yet
registered in shared/actions, nor is an unattended browser job active. A model
being told to browse does not enforce mandatory source receipts.

The current Session admission counter is thread-safe within one host process.
It is not a shared cross-process/profile rate limiter. The existing market-data
QueryPortal is Node/MCP-specific; this candidate does not currently reuse that
queue/retry implementation. Unknown browser-task outcomes remain nonretryable.
Never infer scheduled readiness from the observed foreground read.

## Current bounded development evidence

On 2026-11-01,21 browser component checks and4 evaluator checks passed. A live
owned about:blank fixture completed32 snapshots at concurrency1,2,4,8 (eight
calls per level), with zero marker/amount mismatches. Observed per-level p95
was9.71,9.03,38.23,33.78ms respectively; eight samples per level are descriptive
only. A separate listTaskSpaces check verified the fixture task absent afterward.
The harness made no external site requests. This checks the installed SDK's
owned-page read pressure, not public-page navigation throughput, permission/login
reliability, a cross-process rate limiter, or scheduled readiness. The exact
private receipt is retained under .research-sources/web-access/stress/.

### Matched round-004 and remaining gaps

The newly sealed four-case development trial completed within each arm's
24-operation/360-second ceiling. Native used4 provider items; Ego used16
(three HTML reads at five helper calls each, plus the native PDF control). Native
passed3/4 strict checks; Ego passed1/4. No default adoption or browser superiority
is supported by this result. Billing/reauth/approval counts remain unknown.

Native passed issuer/abstract anchors; the shared native PDF control failed a
literal title pattern because its text layer splits a word with a control
character. Ego's NVIDIA case passed. Its Microsoft snapshot contains all three
anchors but is clipped at120,000 characters. The arXiv snapshot abbreviates an
individual text node, losing the required trainable anchor despite no outer
clipping. A full_page semantic snapshot is therefore not a complete source read.
The existing receipt's truncated flag measures host character clipping only;
per-node SDK abbreviation and omitted content remain possible.

Native observations are reader windows, not full original documents. Two native
HTML reads were batched; their individual latency fields conservatively contain
the whole batch duration and cannot support precise per-case speed claims. This
trial isolates retrieval conformance; it does not test search discovery or Chrome.
All three successful HTML task spaces were independently absent afterward.

An exploratory visible-DOM-text variant was recorded separately. Its first
Microsoft navigation failed; same-space inspection found chrome-error://chromewebdata/.
No new-space retry or successful wrapper result was claimed. Its source bytes
and blocked receipt are retained privately, the prior extractor was restored,
and the closed round-004 source pins validate again. The failed task remains
retained for reconciliation. Do not close/retry it as automatic error recovery.

Next source-quality work is bounded visible-text extraction with URL checks and
a fresh sealed trial, plus a symmetric PDF text-normalization grader repair with
counterexamples. Preserve this completed trial unchanged. Registered-action
integration, profile-wide admission/rate-limit reuse, and future scheduled
acceptance/verified owner notification still require their separate gates.

## Required native slash skill runtime (candidate,2026-11-02)

User acceptance now requires actual runtime slash skill activation. Direct CLI
reads remain lower-layer evidence and cannot satisfy that criterion. Installed
Codex0.166.0 rejects `/ego`; the supported native route is `/skills`, List skills,
select ego-browser. The TUI attaches `$ego-browser` and injects the vendor skill.
The explicit typed skill API is a separate route and is not silently substituted.

`shared/job_runtime/skill_tui.py` owns a bounded real PTY, controlling-terminal
bootstrap, startup device replies and version-pinned selector. It declines
untrusted hooks with bounded Escape attempts; it never trusts hooks or replays
Enter. Automatic Mentor/UI hooks remain unverified. Model input is fenced before
Enter. Native protected history must bind the exact prompt and skill hash and
contain a completed turn; decorative TUI idle/session-ID text is insufficient.
CLI shutdown, owned group cleanup and all failed attempts remain observable.
Native Codex can persist its own private history; raw terminal/model output is
not exported by the driver. Use this first slice for the fixed public probe.

The model sandbox could not directly connect the browser SDK. No full-access
flag or global Codex change was used. `skill_bridge.py` therefore owns one fixed
public vendor-guide read on the host. `skill_client.py` can submit only its
preassigned operation ID. URL/config/script/retry choices are not model input.
Host claims/results are outside the model-writable client directory; forged
client responses cannot satisfy host verification. Timeouts/unknown claims stay
fenced. This is a closed candidate capability, not a general browser proxy or
a newly registered shared/actions entry. Browser network isolation limits still
apply; this is not adversarial OS containment of the external GUI app.

The shared artifact helper now skips a chmod when an ancestor is already0700,
allowing narrow write grants. Insecure ancestors still need a real chmod or fail.
An actual macOS sandbox regression first failed, then passed;117 research-source
checks pass in the existing project environment. No broader write grant was added.

Portable verification and staging use the project environment, with no packages
or services to install beyond the existing common runtime and authorized Ego app:

```sh
.research-sources/.venv/bin/python -B -m unittest shared.job_runtime.tests.test_skill_tui shared.web_access.tests.test_skill_bridge shared.web_access.tests.test_narrow_root -v
.research-sources/.venv/bin/python -B -m shared.web_access.skill_acceptance stage --name scheduled-v1
python3 -B shared/setup_audit.py --refresh
python3 -B shared/setup_audit.py --check
# Register only the newly staged workspace-local once.plist after checks pass:
launchctl bootstrap gui/$(id -u) .job-runtime/acceptance/egolite-slash-20261102/scheduled-v1/once.plist
```

Staging prepares three future once slots60/180/300seconds ahead; it does not
register launchd. Finish documentation/checks before registration and restage
with a new name if the timing window is missed. The temporary allocation uses
the existing common Engine and central auth/model/retry policy; it does not
modify the installed recurring service. Current candidate selection is
research-source-acceptance, GPT-6.1-Sol/low, automatic review, reduced180second
timeout, and one fixed client write root. No auth cache is copied. Auth contention
is retryable before model submission under central bounded backoff. Once submitted,
unverified work is held. The controller stops on a critical failure and retires
its own launchd label after completion. It is not ongoing background monitoring.

Acceptance requires all three future native slash/skill/guide/browser chains,
maximum60second native-turn start lateness, exact candidate fingerprints, separate
guide-before-client calls, independently verified source and absent browser task,
plus verified owner email. A foreground chain now passed these functional checks;
future execution and email remain pending until actual receipts exist. Recurring
production jobs, broad browsing superiority and real signed-in site behavior are
not accepted by this slice.

The final candidate also pins root AGENTS, Mentor startup/router guidance and
workspace Codex configuration. Fifteen focused native-transport/closed-bridge/
narrow-sandbox checks pass. The first staged timing window was not registered
while checks completed; its record is preserved. Fresh scheduled-v2 stages three
future slots under the same criteria. Registration and execution are observed
separately in its private record; staging alone is not a successful runtime run.

Scheduled-v2 failed before any Codex session because the controller omitted
the Engine.tick timestamp. That allocation was retired and its error log retained.
The corrected controller supplies aware current UTC and records a sanitized
permanent failure on an unexpected controller exception; the next tick retires
the allocation instead of looping. Two real-controller entry/fault regressions
pass (seventeen focused checks in total). Scheduled-v3 is a fresh future round;
no old or missed slot is relabeled as successful.

### Observed native-slash acceptance,2026-11-02

Scheduled-v3 completed three real future once runs at01:28:28,01:30:28 and
01:32:28 Shanghai time. Native turn start lateness was6.92575,7.92575 and
3.92575seconds, within the declared60second limit. All three independently
verified literal `/skills` selection, same-hash injected Ego skill, completed
native turn, complete guide before the separate client call (guide output hash
matched the host's actual guide), fixed public source/hash/anchors, absent task
space and CLI/group cleanup. Each had one durable scheduled attempt; no duplicate
source operation was observed. The temporary launchd allocation retired.

Candidate fingerprint: cbe9708d46667bfa9c178a298221f28376aee545acb19599c4bccf462e4b01a4.
Private scheduled-v3/record.json and independent-readback.json preserve slot,
attempt, native thread/turn and source references. Earlier failed/unregistered
rounds remain preserved. Owner notification is a separate exact-readback gate;
its private receipt records synchronization status. This is evidence for three
tested slots of the fixed public probe, not perpetual punctuality, signed-in
site readiness, default-browser adoption or a new production pipeline binding.
The shared/actions browser registration and broader extraction-quality gaps
remain separate work; existing recurring business jobs were not changed.

The configured-owner acceptance summary was sent by the manual supervisor and
its exact recipient, subject and decoded HTML body were verified through Gmail
raw readback. The private scheduled-v3/acceptance.json now records execution
passed and email verified for this tested scope. This is not evidence of a
scheduled business sender or production browser activation.
