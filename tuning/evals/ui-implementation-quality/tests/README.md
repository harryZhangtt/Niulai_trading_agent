This is a synthetic implementation benchmark with twelve observable browser checks and a TypeScript validity gate. These author-created development cases are not secure holdouts. Keep this directory, `gold.json`, and the author reference out of solver packets. Only copy `seed/` and the public `task.md` into a solver's app packet. Freeze and verify the immutable seed files before and after a worker run.

Use only the existing locked local tool graph. From the workspace root, set absolute local paths and invoke the pinned runner:

```sh
export UI_TOOL_ROOT="$PWD/ui/verification"
export BENCH_APP="$PWD/tuning/evals/ui-implementation-quality/seed"
export BENCH_OUTPUT="$PWD/tuning/runtime/ui-implementation-quality-v1/author/example-run"
export BENCH_PORT=5193
export PLAYWRIGHT_BROWSERS_PATH="$PWD/ui/runtime/browsers"
export TMPDIR="$PWD/tuning/runtime/ui-implementation-quality-v1/author/tmp"
export XDG_CACHE_HOME="$PWD/tuning/runtime/ui-implementation-quality-v1/author/cache"
export CI=1
node tuning/evals/ui-implementation-quality/tests/typecheck.cjs
node ui/verification/node_modules/vite/bin/vite.js build --config tuning/evals/ui-implementation-quality/tests/vite.config.mjs
node ui/verification/node_modules/@playwright/test/cli.js test --config tuning/evals/ui-implementation-quality/tests/playwright.config.cjs
```

Use a unique existing output directory for each attempt and an unused local port. The runner owns and stops its Vite process. Vite cache, build output, test receipts, traces and screenshots go to `BENCH_OUTPUT`; temporary browser profiles go to `TMPDIR`. Full Chromium is required on this host. No package installation, network service, personal browser, external account, or active MCP is involved.

`vendor/RevisionTimeline.tsx` is immutable supplied code. Its optional observer is installed by the hidden test at browser initialization and counts actual component executions. The history checksum and visible history still run normally. Q12 asserts at most one extra expensive history execution over twelve unrelated draft keystrokes; it does not require memoization, a particular state manager, a file count, or optimization of inexpensive unrelated elements. The protected export playground drives `NoticePreview` with props and measures API activity independently of the application. No test demands a particular recovery phrase beyond a broad recognizable user-facing state.

Read the JSON result's per-case status. All twelve cases and the TypeScript/build gates are required for a fully passing implementation. Report critical state/write/diagnostic failures individually; an average cannot hide them. Passing these fixture checks is scoped local evidence, not production runtime acceptance, investment-agent performance, a complete accessibility audit, or proof of general skill superiority.
