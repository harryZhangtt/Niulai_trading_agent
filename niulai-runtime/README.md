# Niulai controlled migration runtime

This directory adds tested configuration, Tiger access and email-delivery
boundaries around the preserved `../niulai/` source snapshot. The separate
`shared/job_runtime/` service is installed with readiness allocations and has
completed a one-time full scheduled business test. The existing production cloud
sender has not been replaced.

## Ownership and storage

| Location | Responsibility |
| --- | --- |
| `../niulai/` | Preserved source migration snapshot, read as an explicit dependency |
| `../niulai-private/` | Preserved original private archive; not mutable runtime state |
| `niulai_runtime/config.py`, `scheduler.py` | Configuration validation and schedule admission |
| `niulai_runtime/tiger.py` | Compatibility/report entry point to `../shared/tiger/` |
| `../shared/tiger/` | Shared credential lifecycle, query API and isolated portal |
| `niulai_runtime/delivery.py` | Recipient-bound MIME validation and durable email outbox |
| `niulai_runtime/replay.py` | Manual exact-content migration test and independent Gmail readback |
| `niulai_runtime/wake.py` | Actual-clock shadow schedule check with no source calls or sends |
| `../.niulai-state/` | Git-ignored policies, dependencies, databases, reports, temporary credentials |

Mentor, tuning and investment research are not part of this delivery runtime.
The existing holdings calculation and rendering code is staged privately for a
run, so import-time file creation cannot modify the migration snapshot.

## Current execution boundary

Codex provides the authenticated Sites and Gmail tools. Python does not inherit
these connections. A host operator supplies a fresh Sites result through hidden
stdin and invokes Gmail after an atomic outbox claim. No service bearer is saved
as a scheduler credential. A standalone unattended host still needs supported
authentication adapters and independently verified scheduler ownership.

The manual replay preserves the existing report's historical dates, subject,
HTML and decoded PDF bytes. Its separate request key cannot complete or reopen
a production slot. A successful replay proves transport and content parity,
not a fresh price evaluation or recurring scheduler reliability.

`wake.py` requires a dry-run policy and the real XNYS calendar. A private
`config/schedule-candidate.json` can describe the intended host task, but that
file is a staged specification and never evidence of scheduler installation.

## Dependencies and tests

Use a project-local Python 3.12 environment and the preserved holdings dependency
pins. Configure temporary, Python-install, executable-install and package-cache
directories inside `.niulai-state/`; do not use global package installation.
`requirements.txt` references the source snapshot explicitly. A frozen list of
the installed environment can be kept privately for reproduction; it is not a
cross-platform hash lock.

From the workspace root:

```sh
PYTHONPATH=niulai-runtime PYTHONDONTWRITEBYTECODE=1 \
TMPDIR="$PWD/.niulai-state/tmp" \
.niulai-state/.venv/bin/python -m unittest discover -s niulai-runtime/tests -v
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/tmp" \
.niulai-state/.venv/bin/python -m unittest discover -s shared/tiger/tests -v
```

See [configuration and schedule admission](docs/config-scheduler.md),
[Tiger access](docs/tiger.md), [email delivery](docs/delivery.md), and
[operator procedure](docs/operator.md).

## Cutover gate

Keep the original cloud task active until the replacement execution host is
selected and proves fresh source access, full report generation, accepted email
with independent readback, durable state and an actual unattended due run.
Before enabling a replacement sender, verify the old sender is disabled and
import/reconcile existing delivery records. Never infer those observations from
a configuration flag. The current Python admission interface requires the
operator to supply verified cutover evidence; it cannot verify a cloud task by
itself.

OAuth grant expiry remains a provider constraint. Refresh token persistence can
avoid unnecessary consent but does not renew consent indefinitely. Keep narrow
read-only OAuth scope; do not switch authentication methods to evade expiry.

Official reference: <https://docs-en.itigerup.com/docs/authentication>.

The full scheduled test used native Gmail/Sites from isolated Codex CLI, fresh
source retrieval and Tiger reads, canonical full email/PDF integrity checks, and
independent mailbox readback. Explicit partial data remained visible. A final
model-summary format error was reconciled against actual delivery evidence; no
resend occurred. Future business completion uses the trusted artifact/outbox
postcondition rather than treating the model summary as a delivery receipt.
