#!/usr/bin/env python3
"""Bounded, network-free SessionStart loader for mentor policy and router."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ('development-discipline', 'research-supervisor', 'progress-and-recovery',
          'experiment-design', 'evidence-and-overfitting', 'evaluation-design')
CORE = ('mentor/AGENTS.md', 'mentor/ROUTING.md')
START_SOURCES = frozenset(('startup', 'resume', 'clear', 'compact', 'fork'))
MAX_CONTEXT_BYTES = 12000
MAX_INPUT_BYTES = 65536
MAX_SOURCE_BYTES = 65536
SESSION_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')


def _read_source(root, name):
    path = root / name
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        details = os.fstat(descriptor)
        if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid() or
                details.st_mode & 0o022 or not 0 < details.st_size <= MAX_SOURCE_BYTES):
            raise ValueError('source_safety')
        chunks, remaining = [], details.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                raise ValueError('source_short_read')
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        stable_fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if any(getattr(after, field) != getattr(details, field) for field in stable_fields):
            raise ValueError('source_changed')
        data = b''.join(chunks)
        return data, data.decode('utf-8')
    finally:
        os.close(descriptor)


def _discovery_failure(root, catalog, skill, expected):
    link = root / catalog / 'skills' / skill
    return (not link.is_symlink() or link.resolve() != expected.resolve())


def initialize(root, event):
    root = Path(root).resolve()
    failures, texts, hashes = [], {}, {}
    if event.get('hook_event_name') != 'SessionStart':
        failures.append('unexpected_event')
    source = event.get('source')
    if source not in START_SOURCES:
        failures.append('unexpected_source')
    session_id = event.get('session_id')
    if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
        failures.append('invalid_session_id')
    try:
        Path(event['cwd']).resolve().relative_to(root)
    except (KeyError, OSError, ValueError, TypeError):
        failures.append('workspace_mismatch')

    sources = CORE + tuple('mentor/skills/{}/SKILL.md'.format(skill) for skill in SKILLS)
    for name in sources:
        try:
            data, text = _read_source(root, name)
            if name.endswith('SKILL.md'):
                skill = (root / name).parent.name
                if not re.search(r'^name:\s*' + re.escape(skill) + r'\s*$', text, re.M):
                    raise ValueError('skill_name')
                expected = root / 'mentor/skills' / skill
                if _discovery_failure(root, '.agents', skill, expected):
                    failures.append('codex_discovery:' + skill)
                if _discovery_failure(root, '.claude', skill, expected):
                    failures.append('claude_discovery:' + skill)
            else:
                texts[name] = text
            hashes[name] = hashlib.sha256(data).hexdigest()
        except (OSError, ValueError, UnicodeError):
            failures.append(name)

    if sum(len(text.encode()) for text in texts.values()) > MAX_CONTEXT_BYTES:
        failures.append('context_size_limit')
    if failures:
        notice = 'MENTOR_INIT_FAILED: ' + ', '.join(dict.fromkeys(failures))
        return {
            'continue': True,
            'systemMessage': notice,
            'hookSpecificOutput': {
                'hookEventName': 'SessionStart',
                'additionalContext': (
                    notice + '\nTell the user mentor initialization failed before substantive work. '
                    'Do not claim mentor or router guidance loaded successfully. Read mentor/AGENTS.md '
                    'and mentor/ROUTING.md directly as the disclosed fallback, diagnose the named '
                    'source, and do not silently retry or bypass the failure.'),
            },
        }

    context = (
        'MENTOR_INIT_OK\nMentor policy and router loaded from canonical workspace sources. '
        'Six specialist entrypoints and both Claude/Codex discovery catalogs verified; '
        'load full bodies selectively.\n'
        + '\n'.join('{} sha256={}'.format(name, hashes[name]) for name in CORE)
        + '\n\n'
        + '\n\n'.join('SOURCE: {}\n{}'.format(name, texts[name]) for name in CORE)
    )
    return {
        'continue': True,
        'systemMessage': 'MENTOR_INIT_OK source={}'.format(source),
        'hookSpecificOutput': {
            'hookEventName': 'SessionStart',
            'additionalContext': context,
        },
    }


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError('input_size')
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError('input_shape')
        result = initialize(ROOT, event)
    except Exception:
        result = {
            'continue': True,
            'systemMessage': 'MENTOR_INIT_FAILED: invalid initialization input',
            'hookSpecificOutput': {
                'hookEventName': 'SessionStart',
                'additionalContext': (
                    'MENTOR_INIT_FAILED. Tell the user initialization failed; do not claim '
                    'mentor/router loaded. Use the disclosed direct-read fallback.'),
            },
        }
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    main()
