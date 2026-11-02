"""Offline provenance and resource-closure check; no globals, network or secrets."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit


def read_resource(path, root):
    if path.resolve() != path or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('unsafe resource')
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError('nonregular resource')
        data = source.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError('resource size limit')
    return data


def verify(root):
    errors = []
    try:
        manifest = json.loads(read_resource(root / 'upstream/sources.lock.json', root).decode('utf-8'))
        if not isinstance(manifest, dict) or not isinstance(manifest['repositories'], dict) or not isinstance(manifest['files'], list):
            raise ValueError()
    except (OSError, ValueError, UnicodeError, RuntimeError, KeyError):
        return ['unsafe or invalid provenance manifest']
    seen = set()
    for name, repo in manifest['repositories'].items():
        if not re.fullmatch('[0-9a-f]{40}', repo['commit']):
            errors.append(f'{name}: commit not pinned')
        if repo['license'] not in {'MIT', 'Apache-2.0'}:
            errors.append(f'{name}: unreviewed license')
    for item in manifest['files']:
        path = root / item['path']
        if item['path'] in seen:
            errors.append(f'duplicate path: {item["path"]}')
        seen.add(item['path'])
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            errors.append(f'unsafe path: {item["path"]}')
            continue
        if not path.is_file():
            errors.append(f'missing resource: {item["path"]}')
            continue
        try:
            digest = hashlib.sha256(read_resource(path, root)).hexdigest()
        except (OSError, ValueError, RuntimeError):
            errors.append(f'unsafe or unreadable resource: {item["path"]}')
            continue
        if digest != item['local_sha256']:
            errors.append(f'unreviewed change: {item["path"]}')
        if item['repository'] not in manifest['repositories']:
            errors.append(f'unknown source: {item["path"]}')
    actual = {str(p.relative_to(root)) for p in (root / 'skills').rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    local = set(manifest.get('local_files', []))
    for name in local:
        path = root / name
        if (not name.startswith('skills/') or not path.is_file() or path.is_symlink()
                or not path.resolve().is_relative_to(root.resolve())):
            errors.append('unsafe or missing local resource: ' + name)
    if actual - seen - local:
        errors.append('untracked resource provenance: ' + ', '.join(sorted(actual - seen - local)))
    for page in (root / 'skills').rglob('*.md'):
        try:
            content = read_resource(page, root).decode('utf-8')
        except (OSError, ValueError, UnicodeError, RuntimeError):
            errors.append(f'unsafe or unreadable Markdown: {page.relative_to(root)}')
            continue
        content = re.sub(r'```.*?```', '', content, flags=re.S)
        content = re.sub(r'`[^`\n]+`', '', content)  # Inline literal Markdown examples.
        for match in re.finditer(r'\]\(([^\s)]+)(?:\s+[^)]*)?\)', content):
            target = match.group(1).strip('<>')
            url = urlsplit(target)
            if url.scheme or not url.path:
                continue
            resource = page.parent / unquote(url.path)
            if not resource.resolve().is_relative_to(root.resolve()):
                errors.append(f'escaped link: {page.relative_to(root)}')
                continue
            if not resource.exists():
                errors.append(f'broken link: {page.relative_to(root)} -> {target}')
    return errors


if __name__ == '__main__':
    result = verify(Path(__file__).resolve().parents[1])
    print('\n'.join(result) if result else 'UI_BUNDLE_OK')
    raise SystemExit(bool(result))
