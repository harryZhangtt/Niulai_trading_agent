# UI startup verification — 2026-10-30

The UI category now has a compact SessionStart loader parallel to mentor startup,
seven repository-local discovery links and visible `UI_INIT_OK`/`UI_INIT_FAILED`
protocol statuses. The mentor matcher group was compared before/after and is
unchanged. Only UI policy/router text enters the additional context; reading and
validating seven entrypoints does not preload their bodies.

| Layer | Result | Evidence/limit |
| --- | --- | --- |
| Source/protocol/security checks | 11/11 passed | Happy paths, five start sources, nested cwd, missing/broken/escaped links and resources, malformed metadata/encoding, invalid/oversize/duplicate JSON and sanitized diagnostics. Canonical symlinks to private workspace files are rejected. |
| Existing bundle gate tests | 5/5 passed | Preserved source-integrity and dependency-closure checks. |
| Canonical direct loader invocation | Passed, compact context 4,401 UTF-8 bytes / 980 tokenizer-proxy tokens | Explicitly recorded as direct Python, **not** a host lifecycle event. |
| Fresh isolated Codex app-server catalog | Passed in three directories | Seven canonical enabled skills and one distinct UI SessionStart definition discovered from root, `ui/`, `ui/verification/`. |
| Actual isolated thread startup | Thread created; hook untrusted; no successful UI hook event | `hook_execution_verified=false`; no model turn, trust-hash edit, auth copy or bypass flag. |
| Supported interactive trust review | Not reached | A fresh local Codex home stopped at the sign-in chooser before slash commands; exited without logging in. |
| Running parent host initialization | Unverified | No actual UI SessionStart success output was observed in that existing session. |
| Required scheduled-runtime/email acceptance | Pending | Parent coordinates; source and catalog checks do not satisfy the workspace acceptance contract. |

The actual app-server receipt is
`ui/runtime/init-verification/before-review.json`, with stderr alongside it.
`direct-script-protocol.json` labels its direct-invocation provenance. The test
home/tmp are entirely under `ui/runtime/init-verification/`. No global Codex
configuration or trust cache changed. No credentials were read or copied.

The 980-token figure uses the existing local tiktoken 0.12.0 `o200k_base` utility
and workspace vocabulary cache. It excludes provider/host framing, tool schemas,
reasoning and billed usage; the startup loader itself has no tokenizer dependency.
Only 843 proxy tokens are the two compact source files; the remainder identifies
status and hashes. Full skill bodies are not in this startup payload.

Official [Hooks documentation](https://learn.chatgpt.com/docs/hooks) describes
exact-definition review through `/hooks`, skipping untrusted definitions, and
the warning/context output channels. The pinned local CLI **0.166.0** protocol
schema exposes `hooks/list` but no trust-write RPC. We did not substitute manual
trust-file edits or a bypass flag for supported review.

`UI_INIT_FAILED` continues the session with a visible, sanitized diagnostic so
unrelated work can remain usable. Root instructions still apply. For UI work,
report initialization failure/unverified status before substantive work and
disclose direct policy/router fallback. A skipped/untrusted hook cannot emit a
loader failure marker, so absence of actual output must remain **unverified**.
Success text from tests, quoted instructions or an old report is not current
runtime proof. The synchronous loader is not a background watchdog or release
gate.

Reproduction and the activation boundary are in the
[frontend runbook](../../docs/deployment/frontend.md). Broader UI rendering tests
remain recorded in [the integration report](integration-report.md); their 8/8
result predates and does not prove this new startup/context path. The major
runtime acceptance obligation remains separate and pending.
