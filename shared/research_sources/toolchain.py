"""Explicit local tool references; never depend on an interactive shell shim."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from .artifacts import SOURCE_STATE, private_path, require, save


def configure_node():
    found = shutil.which('node')
    require(found is not None, 'NODE_SETUP_REQUIRED')
    node = Path(found).resolve(strict=True)
    version = subprocess.check_output([str(node), '--version'], text=True, timeout=5).strip()
    require(re.fullmatch(r'v\d+\.\d+\.\d+', version) and int(version[1:].split('.')[0]) >= 22, 'NODE_VERSION_UNSUPPORTED')
    value = {'node': str(node), 'version': version,
             'sha256': hashlib.sha256(node.read_bytes()).hexdigest()}
    ref = save(SOURCE_STATE / 'config', value)
    path = SOURCE_STATE / 'toolchain.json'
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream: json.dump({'toolchain': ref}, stream)
    return ref


def node_binary():
    from .artifacts import read
    ref = json.loads((SOURCE_STATE / 'toolchain.json').read_text())['toolchain']
    value = read(ref); path = Path(value['node'])
    require(path.is_absolute() and path.is_file() and os.access(path, os.X_OK), 'NODE_EXECUTABLE_UNAVAILABLE')
    require(hashlib.sha256(path.read_bytes()).hexdigest() == value['sha256'], 'NODE_EXECUTABLE_CHANGED')
    return str(path)
