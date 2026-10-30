"""Atomic, owner-only local API credential storage; values never enter arguments/logs."""
import json
import os
from pathlib import Path
import tempfile


def save_credentials(location, data):
    location = Path(location)
    if not data or not all(isinstance(value, str) and 0 < len(value) < 1024
                           and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
                           for value in data.values()):
        raise ValueError('Invalid credential input; nothing saved.')
    location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if location.parent.is_symlink() or location.is_symlink():
        raise ValueError('Credential symlinks are not allowed.')
    location.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.credential-', dir=location.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(data, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, location)
    finally:
        Path(temporary).unlink(missing_ok=True)
