# R6 final authority compiler v1 (disabled)

This additive provider-free candidate has one public operation:
`compile_deny_report()`. It verifies fixed repository source pins with exact
path, bytes, SHA-256, mode, owner, and no-follow reads, then returns a DENY
report with a machine-readable missing-pin list. It writes nothing and has no
issuer, writer, signer, reviewer, registry selector, trust-root selector, clock
selector, policy selector, activation, provider, scheduler, network, bytedcli,
or live-execution API.

The exact-pinned runner-v8 independent review and revoked blind-map-v5 review
are verified as `OPEN` blockers, never authority. Blind-map-v5 CLEAN is not
accepted; future blind-map-v6 CLEAN is mandatory. The exact-pinned Codex-v6 boundary
review is CLEAN only pending P0-v10; it is evidence, not authority, and the
separate Codex-v6/P0-v10 pin remains missing. The Draft schemas describe the exact
future block/cell shape but do not mint a grant. Null future digests are
intentionally missing pins. A separate owner and
fresh review must create and exact-pin every future authority, including the
last adoption artifact; this candidate cannot become authoritative by receiving
files alone.
Claude-v8 is exact-pinned as `OPEN` for its closure descriptor mislabel and
requires future Claude-v9 CLEAN. Runner-v2 is exact-pinned as `OPEN` for its
mutable-key and liveness-takeover critical findings and requires both future
runner-v3 CLEAN and P0-v10 CLEAN. Neither OPEN artifact can authorize anything.
Claude-v9 evidence reseal is exact-pinned CLEAN pending P0-v10, but remains
non-authorizing until P0-v10 CLEAN and the fixed final block plus four cell
grant/review pairs exist. Claude-v8 OPEN remains preserved as history.
Runner-v3 is superseded as OPEN for package-reachable key/liveness authority.
Its expected review path is fixed, but bytes/SHA remain unadopted and therefore
missing; future runner-v4 CLEAN plus P0-v10 CLEAN are mandatory.

