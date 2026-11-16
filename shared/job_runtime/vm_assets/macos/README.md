# macOS Virtualization containment helper (source-only candidate)

## Status

**The VM behavior is unexecuted and unaccepted.** This directory is an inert source
candidate. It has not been signed, launched, registered with `launchctl`, connected
to a guest, or exercised with kernel, initramfs, disk, or guest-agent artifacts.
A future owner must perform an explicitly approved, disposable canary and satisfy
the workspace runtime-acceptance contract before making any integration claim.
The helper intentionally fails with a sanitized code on an unsupported macOS host,
a missing `com.apple.security.virtualization` entitlement, invalid artifacts, or a
Virtualization.framework failure.

`guest_agent.py` and this helper share the canonical typed v1 protocol and are tested together.

## Fixed host interface

The only accepted invocation is:

```text
containment-host --request-file <absolute-private-request-path>
```

No request values or sensitive payloads are accepted on the command line. The
request must be a regular, nofollow-opened file owned by the effective user, with
no group/other permission bits, and no larger than 64 KiB. Unknown or missing JSON
keys, duplicate keys (including escaped-equivalent keys), and wrong JSON scalar
types are rejected. `request.schema.json` is the fixed v1 contract;
`Protocol.swift` independently rejects duplicate keys and enforces exact key sets
before `JSONDecoder` is used.

The request's parent is the job authority directory and must itself be owner-only.
Every reference is restricted to a dedicated descendant:

```text
<job>/artifacts/  kernel, initramfs, immutable root disk, initial COW disk
<job>/io/         digest-locked prompt and a new output file
<job>/mounts/     explicit read-only virtiofs source directories
<job>/profiles/   optional digest-locked central unrestricted-NAT profile
<job>/receipts/   a new sanitized teardown receipt
```

Host workspace, home, arbitrary global paths, Unix/control socket paths, writable
virtiofs shares, and implicit mounts are not representable. The only socket
references are two distinct numeric guest virtio ports. All referenced files are
owner-only regular files opened with `O_NOFOLLOW`; all locked SHA-256 digests are
checked before VM configuration. Artifact roles must resolve to distinct inodes.
The helper then creates private APFS clone snapshots, verifies each clone against
the locked digest, and configures VZ only from those pinned paths; clone failure is
a visible hard failure. The snapshots are removed during bounded teardown. The
helper writes output and receipt through same-directory mode-`0600` temporary
files, fsyncs them, publishes with no-overwrite atomic rename, fsyncs the parent,
and rejects aliased destinations.

## VM boundary

One process owns exactly one `VZVirtualMachine`. It never invokes a shell or host
subprocess. The VM is configured with:

- one pinned Linux kernel and initramfs;
- one digest-locked read-only root disk and one digest-locked writable COW disk;
- an in-memory virtio console whose output is drained and never logged;
- one virtio socket device using the fixed stdio and control ports;
- only the request's explicit read-only virtiofs mounts; and
- no network device by default, or NAT only when a digest-locked v1 central profile
  exactly declares `{"profileVersion":1,"mode":"unrestrictedNat"}`.

The helper places no prompt, response, nonce, artifact path, or guest stream data
in logs or the receipt. Standard error receives only a fixed sanitized failure
code. The receipt contains request ID, coarse outcome/timing/byte count, stop-ack and
teardown-confirmed status, and a sanitized code. A forced-stop timeout is recorded
as `teardown_unknown`, never as confirmed cleanup.

## Framing and teardown

Each virtio message is a four-byte unsigned big-endian payload length, one-byte frame type, then payload bytes. The configured `maxFrameBytes` bounds prompt and output frames.
Metadata frames contain exactly `protocolVersion`, `type`, `requestID`, and the
64-hex nonce. The stdio exchange is the typed state machine `FRAME_REQUEST`, zero or more
`FRAME_PROMPT` chunks, `FRAME_PROMPT_END`, zero or more `FRAME_STDOUT` /
`FRAME_STDERR` chunks, `FRAME_EXIT`, then `FRAME_POWEROFF`. `FRAME_CANCEL` is
the sole cancellation/control definition; `FRAME_POWEROFF` is the bounded
stop acknowledgement.

Only after the typed poweroff acknowledgement does the helper request a graceful VM stop. Runtime and shutdown-grace deadlines are bounded; failure causes
a bounded forced-stop attempt and a failed receipt. Process exit is the final
ownership boundary if framework teardown does not complete.

## Source checks and build boundary

`build-source.sh` is compilation-only. It writes the unsigned binary and all Swift
module caches under `.job-runtime/tests/`; it does not sign, install, launch, or
register anything. The source asset root is `shared/job_runtime/vm_assets/macos/`;
the similarly named `shared/job_runtime/macos_vm.py` is a separate Python owner. Signing and entitlement provisioning are deliberately outside
this candidate and require a separate owner decision.

The permitted source check is:

```text
CLANG_MODULE_CACHE_PATH=.job-runtime/tests/swift-module-cache \
SWIFT_MODULECACHE_PATH=.job-runtime/tests/swift-module-cache \
xcrun swiftc -typecheck -module-cache-path .job-runtime/tests/swift-module-cache \
  shared/job_runtime/vm_assets/macos/Protocol.swift \
  shared/job_runtime/vm_assets/macos/ContainmentHost.swift
```

Static tests live at `shared/job_runtime/tests/test_macos_vm_helper.py`. Passing
static tests and typechecking establish source-contract evidence only, not guest,
entitlement, artifact, VM boot, isolation, network, teardown, or production
evidence.
