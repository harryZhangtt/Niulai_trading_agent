"""Offline provenance and resource-closure check; no globals, network or secrets."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def verify(root):
    errors = []
    manifest = json.loads((root / 'upstream/sources.lock.json').read_text())
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
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item['local_sha256']:
            errors.append(f'unreviewed change: {item["path"]}')
        if item['repository'] not in manifest['repositories']:
            errors.append(f'unknown source: {item["path"]}')
    actual = {str(p.relative_to(root)) for p in (root / 'skills').rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    local = {'skills/async-state-reliability/SKILL.md'}
    if actual - seen - local:
        errors.append('untracked resource provenance: ' + ', '.join(sorted(actual - seen - local)))
    for page in (root / 'skills').rglob('*.md'):
        content = re.sub(r'```.*?```', '', page.read_text(), flags=re.S)
        content = re.sub(r'`[^`\n]+`', '', content)  # Inline literal Markdown examples.
        for match in re.finditer(r'\]\(([^\s)]+)(?:\s+[^)]*)?\)', content):
            target = match.group(1).strip('<>')
            url = urlsplit(target)
            if url.scheme or not url.path:
                continue
            if not (page.parent / unquote(url.path)).exists():
                errors.append(f'broken link: {page.relative_to(root)} -> {target}')
    return errors


if __name__ == '__main__':
    result = verify(Path(__file__).resolve().parents[1])
    print('\n'.join(result) if result else 'UI_BUNDLE_OK')
    raise SystemExit(bool(result))
