"""Isolated v5 worker: stdlib verification precedes every repository import."""
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

HEX = frozenset("0123456789abcdef")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fail(code):
    raise RuntimeError(code)


def exact_read(path, expected):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        fail("RUNNER_V5_SNAPSHOT_OPEN_FAILED")
    try:
        meta1 = os.fstat(fd)
        if not stat.S_ISREG(meta1.st_mode) or meta1.st_nlink != 1:
            fail("RUNNER_V5_SNAPSHOT_FILE_UNSAFE")
        chunks, total = [], 0
        while True:
            part = os.read(fd, 65536)
            if not part:
                break
            total += len(part)
            if total > expected["bytes"]:
                fail("RUNNER_V5_SNAPSHOT_SIZE_MISMATCH")
            chunks.append(part)
        meta2 = os.fstat(fd)
    finally:
        os.close(fd)
    raw = b"".join(chunks)
    if (meta1.st_dev, meta1.st_ino, meta1.st_size, meta1.st_mtime_ns) != (meta2.st_dev, meta2.st_ino, meta2.st_size, meta2.st_mtime_ns):
        fail("RUNNER_V5_SNAPSHOT_READ_DRIFT")
    if len(raw) != expected["bytes"] or sha(raw) != expected["sha256"]:
        fail("RUNNER_V5_SNAPSHOT_PIN_MISMATCH")
    return raw


def verify_snapshot(root, manifest):
    rows = manifest["files"]
    for row in rows:
        exact_read(root / row["path"], row)


def validate_loaded(root, manifest):
    expected = {row["path"] for row in manifest["files"] if row["group"] == "python"}
    loaded = set()
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        try:
            path = Path(filename).resolve()
        except OSError:
            continue
        if root in path.parents and path.suffix == ".py":
            loaded.add(path.relative_to(root).as_posix())
    extra = loaded - expected
    if extra:
        fail("RUNNER_V5_UNMANIFESTED_IMPORT:" + ",".join(sorted(extra)))
    required = set(manifest["required_loaded_python"])
    if not required.issubset(loaded):
        fail("RUNNER_V5_REQUIRED_IMPORT_MISSING")


class DescriptorBoundary:
    def __init__(self, arm, value, claude_adapter, codex_adapter):
        self.mode = value.get("mode")
        self.counter = None if value.get("counter_path") is None else Path(value["counter_path"])
        self.crash_first = value.get("crash_first") is True
        factory = claude_adapter if arm == "ARM-A" else codex_adapter
        self.adapter = factory(Path(value["owner_root"]), Path(value["public_root"]))

    def __call__(self, _plan):
        fail("RUNNER_V5_PARENT_BOUNDARY_MUST_NOT_EXECUTE")


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "--snapshot-root":
        return 70
    root = Path(sys.argv[2]).resolve()
    try:
        raw_manifest = (root / "shared/job_runtime/candidates/r6_data_quality_2x2_runner_v5/manifest-v5.json").read_bytes()
        manifest = json.loads(raw_manifest.decode("ascii"))
        if canonical(manifest) != raw_manifest:
            fail("RUNNER_V5_MANIFEST_NOT_CANONICAL")
        verify_snapshot(root, manifest)
        sys.path.insert(0, str(root))
        from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v4 import runner as v4
        from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.adapters import claude_adapter, codex_adapter
        verify_snapshot(root, manifest)
        validate_loaded(root, manifest)
        request_raw = sys.stdin.buffer.read(1_048_577)
        if len(request_raw) > 1_048_576:
            fail("RUNNER_V5_REQUEST_SIZE")
        request = json.loads(request_raw.decode("ascii"))
        if canonical(request) != request_raw or type(request) is not dict:
            fail("RUNNER_V5_REQUEST_NOT_CANONICAL")
        payload = request["payload"]
        if request["operation"] == "execute":
            descriptors = payload["fixture_boundaries"]
            if request.get("fault") == "exit42_after_first_boundary":
                descriptors = {k: dict(v) for k, v in descriptors.items()}
                descriptors["ARM-A"]["crash_first"] = True
            boundaries = {arm: DescriptorBoundary(arm, descriptors[arm], claude_adapter, codex_adapter) for arm in ("ARM-A", "ARM-B")}
            reservation_fault = {
                "exit43_pre_admission": "crash_after_reservation",
                "exit43_after_admission": "crash_after_admission",
            }.get(request.get("fault"))
            receipt_fault = {
                "exit44_after_stage_fsync": "crash_after_stage_fsync",
                "exit44_post_link": "crash_post_link",
            }.get(request.get("fault"))
            result = v4.execute_block(
                payload["authority_registry_ref"], Path(payload["owner_root"]),
                payload["map_commitment_ref"], Path(payload["bundle_root"]),
                _fixture_boundaries=boundaries, _reservation_fault=reservation_fault,
                _receipt_fault=receipt_fault,
            )
        elif request["operation"] == "finalize":
            result = v4.finalize_block(
                payload["execution_ref"], Path(payload["owner_root"]),
                payload["grade_refs"], payload["opening_ref"],
            )
        else:
            fail("RUNNER_V5_OPERATION")
        verify_snapshot(root, manifest)
        validate_loaded(root, manifest)
        sys.stdout.buffer.write(canonical({"result": result}))
        sys.stdout.buffer.flush()
        return 0
    except BaseException as exc:
        text = str(exc)
        for code in (42, 43, 44):
            if "RUNNER_V4_CHILD_EXIT_%d" % code in text:
                os._exit(code)
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
