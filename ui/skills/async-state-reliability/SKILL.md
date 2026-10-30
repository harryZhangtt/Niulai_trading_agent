---
name: async-state-reliability
description: "Implement or review entity-scoped React/TypeScript drafts, asynchronous reads and mutations, including stale responses, duplicate actions, validation failure and unknown write outcomes. Use for interactive state correctness, not static visual styling."
---

# Async state and failure contracts

Separate server state, entity/edit-session drafts and transient interaction state.
Reuse the application's state libraries. Add a library only when a concrete need
outweighs migration and maintenance costs. Query keys include entity identity;
consume cancellation signals and still guard late responses by request/session
identity. A late response for A must not replace B or erase B's draft.

Represent loading, editing, saving, failed and uncertain-result states explicitly.
Acquire an immediate in-flight guard before awaiting a save; a disabled button
alone is not a business idempotency guarantee. Associate each operation ID with
its immutable entity and payload. The server owns durable idempotency across
tabs/restarts. Scope success/failure to the initiating edit session.

Validate before mutation and preserve the user's draft after validation or
network failure. Show useful recovery and field errors with accessible labels
and focus. Do not replace error feedback with raw provider exception text.
Render boundaries catch rendering failures; handle ordinary event-handler and
async failures explicitly at their I/O boundaries.

A lost response after a write is an unknown result. Keep its operation ID,
reconcile status or replay the same key only under the server's idempotency
contract. Do not create a new business operation merely because a timeout fired.
Bound read/reconciliation retries and show uncertainty honestly. Keep credentials
server-only; use synthetic error canaries when testing diagnostics.

Before claiming robustness, reproduce applicable outcomes through the rendered
interface: A→B with A late; rapid duplicate Save; accepted write with lost response
and reconciliation; draft retention after validation/network failure; keyboard
focus, narrow layouts, empty states and reduced motion. Assert business operation
counts and final entity state, not just a toast or screenshot. Fixture/mock tests
prove their scoped contract; actual service and application acceptance are
separate. Put regressions alongside the affected component.

Authoritative behavior references: [React boundaries](https://react.dev/reference/react/Component#catching-rendering-errors-with-an-error-boundary),
[TanStack Query cancellation](https://tanstack.com/query/latest/docs/framework/react/guides/query-cancellation),
[React Hook Form submission](https://react-hook-form.com/docs/useform/handlesubmit).
These are implementation options, not mandatory dependencies.

