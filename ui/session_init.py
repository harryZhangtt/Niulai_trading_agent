#!/usr/bin/env python3
"""Bounded, network-free SessionStart loader for compact UI policy and routing."""
import hashlib
import json
from pathlib import Path
import sys

if __package__:
    from .route import RouteError, read_catalog, read_source, valid_entrypoint
else:
    from route import RouteError, read_catalog, read_source, valid_entrypoint

ROOT = Path(__file__).resolve().parents[1]
# Retain a public discovery list for the standalone catalog verifier. Runtime
# initialization re-reads the selected workspace's bounded catalog and fails
# visibly if it is invalid; an import-time error must not break hook JSON output.
try:
    SKILLS = tuple(read_catalog(ROOT)['skills'])
except RouteError:
    SKILLS = ()
CORE = ('ui/AGENTS.md', 'ui/ROUTING.md')
SOURCES = ('startup', 'resume', 'clear', 'compact', 'fork')
MAX_INPUT_BYTES = 65536
MAX_SOURCE_BYTES = 65536
MAX_CONTEXT_BYTES = 10000


def failed(codes):
    notice = 'UI_INIT_FAILED: Harry UI skill set could not be enabled; ' + ', '.join(codes)
    return {'continue': True, 'systemMessage': notice,
            'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext':
                notice + '\nTell the user UI initialization failed before substantive UI work. '
                'Do not claim the UI router loaded. Diagnose the named local source/link; '
                'use root safety rules and disclose any direct-file fallback. '
                'A skipped/untrusted hook or missing actual output is unverified, not success.'}}


def initialize(root, event):
    root = root.resolve()
    failures, texts, hashes = [], {}, {}
    try:
        skills = tuple(read_catalog(root)['skills'])
    except RouteError:
        return failed(['ui/catalog.json'])
    if not isinstance(event, dict):
        return failed(['invalid_input'])
    if event.get('hook_event_name') != 'SessionStart':
        failures.append('unexpected_event')
    if event.get('source') not in SOURCES:
        failures.append('unexpected_source')
    try:
        cwd = Path(event['cwd'])
        if not cwd.is_absolute() or not cwd.resolve().is_relative_to(root):
            raise ValueError()
    except (KeyError, ValueError, TypeError):
        failures.append('workspace_mismatch')
    for name in CORE + tuple('ui/skills/{}/SKILL.md'.format(s) for s in skills):
        path = root / name
        try:
            data = read_source(path, root, MAX_SOURCE_BYTES)
            content = data.decode('utf-8')
            if name.endswith('SKILL.md'):
                skill = path.parent.name
                if not valid_entrypoint(content, skill):
                    raise ValueError()
                link = root / '.agents/skills' / skill
                if not link.is_symlink() or link.resolve() != path.parent.resolve():
                    raise ValueError()
            else:
                texts[name] = content
            hashes[name] = hashlib.sha256(data).hexdigest()
        except (OSError, ValueError, UnicodeError, RuntimeError):
            # Only canonical relative names are emitted; no input/path/content echo.
            failures.append(name)
    if sum(len(t.encode()) for t in texts.values()) > MAX_CONTEXT_BYTES:
        failures.append('context_size_limit')
    if failures:
        return failed(failures)
    notice = ('UI_INIT_OK: Harry UI routing resources are ready for this session '
              '({} skill sources and discovery links verified).'.format(len(skills)))
    context = (notice + '\nThis checks resources, not durable opt-in. Only a successful native-thread '
               'activation or restore may attest enabled mode. Load bodies selectively.\n'
               + '\n'.join('{} sha256={}'.format(name, hashes[name]) for name in CORE)
               + '\n\n' + '\n\n'.join('SOURCE: {}\n{}'.format(name, texts[name]) for name in CORE))
    return {'continue': True, 'systemMessage': notice, 'hookSpecificOutput': {
        'hookEventName': 'SessionStart', 'additionalContext': context}}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate input field')
        result[key] = value
    return result


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError('input too large')
        event = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object)
        result = initialize(ROOT, event)
    except Exception:
        result = failed(['invalid_initialization_input'])
    print(json.dumps(result))


if __name__ == '__main__':
    main()
