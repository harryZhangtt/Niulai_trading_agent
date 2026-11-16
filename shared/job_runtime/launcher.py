"""Source-only service launcher used by the generated host arguments.

Python executes this file as a script from source.  It then reads one bounded,
owner-controlled service.py inode and executes those exact bytes, so timestamp
based bytecode is never consulted before service attestation.
"""
import hashlib
import os
from pathlib import Path
import stat
import sys

_MAX_SERVICE_SOURCE = 4 * 1024 * 1024


def _open_held(path):
    """Open a file through no-follow directory descriptors held until close."""
    path = Path(path)
    descriptors = [os.open(path.anchor if path.is_absolute() else '.',
                           os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))]
    components = path.parts[1:] if path.is_absolute() else path.parts
    try:
        for descriptor in descriptors:
            info = os.fstat(descriptor)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.getuid()) or
                    info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
                raise OSError('untrusted source directory')
        for component in components[:-1]:
            if component in ('', '.', '..'):
                raise OSError('invalid source path')
            descriptors.append(os.open(
                component, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
                getattr(os, 'O_NOFOLLOW', 0), dir_fd=descriptors[-1]))
            info = os.fstat(descriptors[-1])
            if (info.st_uid not in (0, os.getuid()) or
                    info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
                raise OSError('untrusted source directory')
        descriptor = os.open(components[-1], os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0),
                             dir_fd=descriptors[-1])
        return descriptor, descriptors
    except BaseException:
        for held in reversed(descriptors):
            os.close(held)
        raise


def _service_snapshot(path):
    descriptor = None
    parents = []
    try:
        descriptor, parents = _open_held(path)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) or
                not 0 < info.st_size <= _MAX_SERVICE_SOURCE):
            raise RuntimeError("SERVICE_SOURCE_INVALID")
        chunks = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(131072, remaining))
            if not chunk:
                raise RuntimeError("SERVICE_SOURCE_INVALID")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if ((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
            raise RuntimeError("SERVICE_SOURCE_CHANGED")
        return b"".join(chunks)
    except OSError:
        raise RuntimeError("SERVICE_SOURCE_INVALID") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for held in reversed(parents):
            os.close(held)


def main():
    service_path = Path(__file__).with_name("service.py")
    source = _service_snapshot(service_path)
    os.environ["_JOB_RUNTIME_EXACT_SOURCE"] = "1"
    scope = {
        "__name__": "__main__",
        "__file__": str(service_path),
        "__package__": "shared.job_runtime",
        "__builtins__": __builtins__,
        "_EXECUTED_SOURCE_SHA256": hashlib.sha256(source).hexdigest(),
    }
    exec(compile(source, str(service_path), "exec", dont_inherit=True), scope)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
