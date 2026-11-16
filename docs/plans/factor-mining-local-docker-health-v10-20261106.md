# Factor-mining local Docker health lifecycle v10

**Status:** selected-disabled — 2026-11-06

## Goal

Validate one smallest disposable local-container path before resolving RD-Agent/Qlib images: pinned base pull, source-only image build, hard containment declarations, one health command, host receipt publication, and cleanup. No scientific or provider work is in scope.

## Boundaries

- Existing reconciled Colima profile: `factor-mining`, evidence `95b18403e961557f3968407fb39a2c481ea751472039cb09ec14435c4eefc910`.
- Python base index: `sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39`.
- Linux/arm64 manifest: `sha256:464bee9ac10a34b0c86031f12d94d7ccc4643725773b23eff4076305fafab420`.
- One health-only standard-library worker; `execute` remains blocked.
- Host Docker context is always explicit; global context is unchanged.
- No network, mounts, secrets, Docker socket, privilege, mutable image reference at execution, or automatic restart.

## Lifecycle and failure contract

The host runs pull → build with `--pull=false` → inspect immutable image ID → create → inspect → start → wait → bounded logs → terminal inspect → atomically publish private receipt → remove. The container remains after any uncertain post-create failure. Timeout, daemon disconnect, malformed output, or missing inspection is unknown and not retryable. `--rm` is forbidden.

## Resource envelope

This health fixture is limited to 0.5 CPU, 256 MiB memory with no additional swap, 128 PIDs, 64 MiB `/tmp`, 16 MiB `/run`, and local logs of 10 MiB × 3. It proves only declared and later inspected controls, not scientific capacity. Default scientific executor concurrency remains one; burst two is untested.

## Acceptance

Before activation: exact schemas and source hashes, adversarial argv tests, receipt-before-remove proof, and independent review. Intended-runtime acceptance later requires real create/inspect/start/wait/log/receipt/remove, forced post-create uncertainty, cancellation/cleanup, zero leaked containers/networks, and VM stop after queue drain.

## Nonclaims

This does not build or run RD-Agent/Qlib, generated code, market data, evaluator/checker, factor quality, autoscaling, preemption, or production scheduling. It does not resolve scientific image/release blockers or substitute for future scheduled runtime/email acceptance.
