"""Load trust implementations from stable held bytes, never timestamp bytecode."""
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import sys


def load_exact(name, path):
    """Publish one canonical module whose digest covers the bytes compiled here.

    Called by package initialization before ordinary child imports. An already
    published child is rejected rather than replaced (which would split identity).
    """
    if name in sys.modules:
        raise ImportError('EXACT_SOURCE_ALREADY_LOADED')
    path = Path(path).absolute()
    held = []
    try:
        held.append(os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY))
        for part in path.parts[1:]:
            parent_info = os.fstat(held[-1])
            if (not stat.S_ISDIR(parent_info.st_mode) or
                    parent_info.st_uid not in (0, os.getuid()) or parent_info.st_mode & 0o022):
                raise ImportError('EXACT_SOURCE_DIRECTORY_INVALID')
            held.append(os.open(part, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=held[-1]))
        before = os.fstat(held[-1])
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or
                before.st_mode & 0o022 or not 0 < before.st_size <= 4 * 1024 * 1024):
            raise ImportError('EXACT_SOURCE_INVALID')
        source = b''
        while len(source) < before.st_size:
            chunk = os.read(held[-1], before.st_size - len(source))
            if not chunk:
                raise ImportError('EXACT_SOURCE_TRUNCATED')
            source += chunk
        def identity(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if identity(before) != identity(os.fstat(held[-1])):
            raise ImportError('EXACT_SOURCE_CHANGED')
        digest = hashlib.sha256(source).hexdigest()
        code = compile(source, str(path), 'exec', dont_inherit=True)
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        module.__dict__['_EXECUTED_SOURCE_SHA256'] = digest
        sys.modules[name] = module
        try:
            exec(code, module.__dict__)
            if identity(before) != identity(os.fstat(held[-1])):
                raise ImportError('EXACT_SOURCE_CHANGED')
        except BaseException:
            sys.modules.pop(name, None)
            raise
        parent, _, child = name.rpartition('.')
        setattr(sys.modules[parent], child, module)
        return module
    finally:
        for descriptor in reversed(held):
            os.close(descriptor)
