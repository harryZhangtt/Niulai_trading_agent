# Registered research actions

`shared.actions` provides a small typed execution boundary around existing public
source and numeric-comparison code. It adds no provider SDK, general shell tool,
model loop, active MCP registration or credential handling.

Use the existing research environment:

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m shared.actions catalog
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m unittest discover -s shared/actions/tests -v
```

`resolve(selector)` returns the exact descriptor, current release manifest and
`release_sha256`. Bind that hash into each request at run start. Selectors are
`evidence.acquire_document@1`, `evidence.read@1`, and
`evidence.compare_numeric@1`; exact `@1.1.1` is also accepted. Version 1.1.0
added the optional frozen-release protocol. Earlier 1.0.0 working-tree receipts
remain historical evidence; no original immutable bundle is invented for them.

```text
request = {
  schema_version: 1,
  action: selector,
  request_id: application_generated_id,
  arguments: action_specific_object,
  expected_release_sha256: resolved_release_sha256
}
```

- Acquisition arguments: `{kind: arxiv | official_document, value: ID_or_URL}`;
  success data is `{source_ref: {path, sha256}}`.
- Read arguments: `{source_ref, start?, max_chars?}`; success data contains the
  same reference and a bounded exact-offset passage.
- Comparison arguments: `{packet_ref}`; success data is the preserved numeric
  comparison result. A disagreement or incomparable unit is a domain finding,
  not an execution failure or a reason to retry.

`dispatch(request, output_directory=...)` validates, executes and validates the
result in-process. It has no independent wall-time guarantee. For runtime use,
`invoke(request, output_directory=..., timeout_seconds=45)` supervises an actual
worker subprocess with output/deadline limits and process-group cleanup. The
worker accepts `{request, output_directory}` on stdin through
`python -m shared.actions worker`. Output directories are application-selected
and must pass the existing private artifact containment checks.

Outcomes have `schema_version`, `status` (`success`, `partial`, `failure`), `data`,
`error` and `execution_ref`. Partial is reserved by the common contract; current
wrappers either return validated data or explicit failure. Failure records carry
stable codes, retryability and effect uncertainty. The executor owns no retry
loop; source and domain owners retain their policies. Timeouts preserve an
unknown-outcome execution receipt and never automatically replay a write.

For a run that must survive source edits, freeze its actions before execution:

```python
release = freeze_release("evidence.compare_numeric@1", directory=private_directory)
request["release_ref"] = release["release_ref"]
request["expected_release_sha256"] = release["release_sha256"]
outcome = invoke(request, output_directory=private_output)
```

`freeze_release` captures only the registered action code, schemas, explicit
source helpers and numeric dependency into a content-addressed, read-only local
bundle. It copies no credentials, observations, environment or whole repository.
Use one persistent release directory as the local publication catalog. Atomic
first-publication records reject different bytes under an already published
action version in that catalog; publish a new version after changing code.
Separate directories are separate catalogs, not a global signed authority.
The returned descriptor includes a hash-bound `schema_registry_ref`; phase
configuration must use those frozen argument schemas when interpreting an old
release. `resolve(selector, release_ref=...)` reads the historical descriptor.
Current catalog retirement prevents new freezes/resolution but does not rewrite
an existing pinned bundle. A release reference is selected by trusted application
code, not accepted as a code-publication instruction from model arguments.

Frozen workers use Python isolated mode, verify every bundled file, and import
only the staged public package. The bootstrap explicitly restores the trusted
original workspace data roots; the numeric implementation resolves from the
staged source root. Input and output artifact references therefore keep their
original locations instead of silently relocating beneath the bundle.

Manifests pin the selected public local source, schemas, interpreter hash,
Python/jsonschema/rfc3339-validator versions and dependency specification.
Bundles are checked before and after execution; tampering rejects publication.
Read-only modes and hashes provide cooperative local immutability, not an OS
security sandbox, signed publication or a fully immutable transitive dependency
environment. The original installed third-party environment must remain
compatible. No automatic package installation or migration occurs.

Requests without `release_ref` retain pre/post working-tree integrity behavior
and fail closed on drift. Exact historical execution requires its original
frozen bundle. `dispatch` routes a frozen request through the same supervised
worker as `invoke`, rather than importing historical code into the parent.

No source truth or independence follows from successful execution. Evidence CRUD,
claim-specific use permission, financial interpretation and final completion
remain in their respective owners. Component tests do not replace the required
future scheduled-session acceptance and verified owner notification.


Version 1.1.1 tightens the atomic boundary: arguments/limits are checked before
worker creation; returned data must match the selected action contract; receipt
request/data/action/error/release bindings are checked; owned process groups are
cleaned before reaping the leader. Frozen descriptor metadata must match the
literal registry inside its hash-verified bundle. HTTP 200 service/authentication
error pages are rejected by the captured fetcher. Existing genuine 1.1.0 bundles
remain readable; published contents are not overwritten. Registered subprocess
cleanup is not an adversarial sandbox, and a child creating a separate session
is outside its original process group.
