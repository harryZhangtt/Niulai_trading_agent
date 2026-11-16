# R6 final authority compiler v2 (disabled)

This additive provider-free candidate exposes exactly one public name and callable:
`compile_deny_report()`. It verifies only fixed repository pins using exact path,
bytes, SHA-256, mode, owner, duplicate-key rejection, and descriptor-relative
no-follow reads. It always returns a DENY report and writes nothing.

The exact 15-member v1 snapshot identities and pinned OPEN review remain immutable
history. Post-review v1 worktree bytes are `MUTATED_SUPERSEDED_HISTORY`, never
authority or predecessor-clean, and are not imported. The exact v1 review is
itself an OPEN blocker, never authority. Current blind-map
v5, v6, runner-v2, runner-v3, runner-v8, and Claude-v8 OPEN reviews remain blockers. Blind-map-v6 can never authorize; only future blind-map-v7 CLEAN is eligible. Codex-v6
and Claude-v9 are exact-pinned CLEAN evidence only, remain nonauthorizing, and
require P0-v10 reclosure. Runner-v3 is exact-pinned OPEN for package-reachable key/liveness authority and
remains a verified nonauthority blocker; runner-v4 is now exact-pinned OPEN for unpinned import authority, parent closure-cell acceptance bypass, and delayed UNKNOWN. Only future runner-v5 CLEAN plus P0-v10 can satisfy the runner successor chain. The full final execution-window-v2 seven-finding review supersedes the earlier single-finding artifact and is exact-pinned OPEN. Execution-window-v3 fixes only the Boolean mismatch and remains disabled, unreviewed nonauthority evidence; it can never authorize. The required future window is exclusively execution-window-v4 at `tuning/architecture/r6_common_execution_window_v4/independent-review-v4-clean.json` with verdict `CLEAN_EXECUTION_WINDOW_V4`; its bytes and SHA-256 remain null, so the compiler remains DENY.

The package has no CLI, writer, issuer, signer, reviewer, installer, grant,
adoption, activation, provider, scheduler, network, bytedcli, or live-execution
API. Root-level Draft 2020-12 schemas are strict and nonauthorizing. Draft
validators exist only in tests and are unreachable from the package public
surface. A separate owner and fresh independent review are required before any
subsequent candidate claim.

Claude metadata-preflight-v1 is exact-pinned OPEN and can never authorize. Only a future metadata-preflight-v2 CLEAN review at the fixed additive architecture path can satisfy that successor slot.
