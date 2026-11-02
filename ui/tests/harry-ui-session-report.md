# Harry UI session wrapper and lightweight intent test

Historical initial-wrapper report. Its conversational-retention/explicit-only
implementation was superseded by the [durable runtime verification](../portable/runtime_verification/report.md).
Keep these original measurements and source pins as that earlier revision's
evidence, not proof of the current package's persistence.

The user authorized cross-repository exposure after intent/token testing on
2026-11-02. The validated package is installed for this account at
`~/.agents/skills/harry-ui-skill-set`. It is a self-contained copy with **one**
discoverable entrypoint and **22** internal expert `GUIDE.md` resources. It does
not link back to the Trading Agent checkout. The supported user-scope location
and explicit invocation syntax are documented in
[OpenAI's skills guide](https://learn.chatgpt.com/docs/build-skills).

## Once per conversation

Invoke `$harry-ui-skill-set`. Its activation command validates the installed
bundle and target, emits `HARRY_UI_SESSION_ENABLED`, and directs Codex to say:

> Harry UI skill set is enabled for this session. I'll select the relevant UI
> skills as we work and report missing tools or failed checks.

The agent retains the activation marker/fingerprint and intent card in the
conversation, including context handoffs. Later tasks use that context without
another invocation. A new conversation starts fresh; disabling is also scoped to
the conversation. No shared enable flag, daemon or global hook is installed.
The existing Codex session interprets the small card; a local standard-library
selector validates decisions and returns guide paths. There is no additional
classifier model call in this normal workflow.

Actual explicit activation succeeded in this current conversation. Independently,
a fresh client activated from the installed package in a separate Git root; its
next turn, without another invocation, selected async-state reliability,
Impeccable hardening, React performance and Playwright for a race/render issue.
It selected no UI procedure for a backend-only migration. This is a two-turn
instruction-retention check, not a platform-persisted setting or lifetime guarantee.
Source tests also exercise corrupt activation and no-write behavior.

The repository SessionStart success message now explicitly says the Harry UI
skill set is enabled, and asks Codex to announce it once. That source/protocol
path passes tests. **Automatic host hook execution remains unverified**; a manual
activation or direct loader test is not that proof. Missing tools such as Pencil
remain blocked even in an enabled conversation.

## Intent classification before publication

The subagent froze realistic requests, gold, critical rules, identical per-arm
budgets and source hashes before dispatch. Classifiers received only instructions,
request batches and a minimal decision schema, with tools disabled and no gold.
Existing runtime evidence contracts gate dispatch and completion. Four real
calls were preserved using the existing configured profile; no fallback/retries.

| Final v2, fresh validation batch | Full router | Lightweight card |
| --- | ---: | ---: |
| Correct intents | 12/12 | 12/12 |
| Critical misses / extra guides | 0 / 0 | 0 / 0 |
| Instruction token proxy | 1,083 | 541 |
| Reported input tokens | 24,748 | 24,206 |
| Reported output tokens | 324 | 331 |
| Reported input + output | 25,072 | 24,537 |
| Batch wall time, one observation | 15.82 s | 13.67 s |

Policy text fell **50.05%**, but reported whole-call input-plus-output fell only
**2.13%** because common host context dominates. Output/reasoning rose slightly;
there is no dollar-billing or stable-latency claim. This benchmark excludes
activation-wrapper text and subsequent expert-body loads. Selected-body bytes
were equal across these validation arms, not measured model consumption.

V1 failed development: 23/24 versus 24/24, adding a web-browser guide for an
unavailable native Pencil task. It also added permitted but overlapping layout
guidance, increasing hypothetical later guide bytes. The narrow repair makes
native-vs-web verification and overlapping guidance explicit. V1's rejected
attempt remains preserved; v2 was frozen before root saw the fresh 12 cases.
Do not combine these into a 36-case v2 accuracy score. Small synthetic batches
and one profile do not establish universal accuracy or superiority.

The [full evaluation report](../../tuning/evals/ui-intent-lightweight/report.md)
contains budgets, raw-trace references, all four attempts (101,158 reported
input-plus-output tokens), separate reasoning/cached counters, grader limitations
and source hashes. Requested profile was `gpt-6.1-sol`/low; the CLI did not emit an
independently observed backend model identifier.

## Installation and operational checks

The final package's intent-card SHA-256 is
`ec9c8d4f1ad404ff337806032c17c6a8ba86bd987cec6076af61f2f57e477c03`,
identical to the validated card. Published manifest SHA-256 is
`81fae3929fe8ad0df654625c63409f11be97051c9be0e34bda51b4520e02df8f`.

- **13/13** portable package checks pass: copied-bundle execution, single
  discovery identity, corruption/no-write activation, aliases/dependencies,
  missing-tool status, atomic no-overwrite publication and owned rollback.
- **13/13** repository startup checks pass, including bounded file failures and
  the meaningful success message. **5/5** intent-grader boundary checks pass.
- Fresh Codex `skills/list` finds the installed wrapper with **user** scope in
  two independent Git roots and this checkout; zero bundled experts leak into
  discovery. This test made no model call or global configuration change.
- Installed UI/UX search runs successfully from another Git root. Browser/app
  helpers require that target's actual toolchain; portable prerequisite checks
  are not proof of browser execution in every repository.
- Twelve deterministic selector subprocesses measured **30.203 ms median**,
  **34.586 ms maximum** on this machine. This excludes natural-language model
  work and is not an end-to-end request latency benchmark.

Context-size proxies (`o200k_base`): the installed metadata name/description/path
is **64** tokens, selected wrapper body **501**, intent card **541**. Normal
discovery exposes metadata; explicit activation reads the wrapper and card, not
all expert bodies. The repository-specific startup payload measured **1,660**,
below its configured 2,000-token proxy threshold. These are serialized-text
proxies, not actual full-session billing.

No global settings, shell profiles, MCP registration, browser or dependency was
installed. The only authorized external publication is the owned skill payload
and its receipt. Target repositories own runtime state/tools. Helper containment
is partly procedural, not an OS sandbox. Hallmark resource-authoring operations
are disabled in the portable copy; Design MD validates target prerequisites
inside its sanitized error boundary. Native Pencil, optional provider/media
APIs and full Hallmark Puppeteer rendering retain their documented limits.

Private machine receipts live under `ui/runtime/harry-ui-20261102/`:
`install-result.json`, `discovery/result.json`, `session-probe/`,
`current-session-activation.json`, `selector-timing.json`, `context-proxies.json`
and `final-tests.log`. See [the frontend runbook](../../docs/deployment/frontend.md)
for exact build/install/rollback commands. Automatic/future-scheduled runtime
acceptance and its owner notification are recorded separately under
`.job-runtime/acceptance/harry-ui-skill-set-20261102/`; manual successes do not
substitute for that gate. The manual supervisor notice was sent to the validated
configured owner and its exact recipient/subject/HTML readback verified.
