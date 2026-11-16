# Duplicate-safe local activation probe parsing v8

Date: 2026-11-06

Status: **selected-disabled**

V8 preserves v7 process, timeout, workspace identity, socket containment and
reconciliation logic. Its only delta is strict decoding of both fixed probe
outputs before any semantic decision.

Each output is bounded to 65,536 bytes and decoded by the duplicate-key,
non-finite and Unicode-safe strict loader. Duplicate last-key-wins payloads,
NaN/Infinity, invalid UTF-8, surrogate strings, malformed/trailing JSON and
oversized documents are rejected with sanitized v8 errors. Colima remains exact
`{"profile":"factor-mining","status":"Running"}`; Docker context retains the
v7 existing-socket and strict containment requirements.

Tests patch the fixed command helper only; no Colima or Docker command runs.
Passing this gate does not establish actual runtime readiness.
