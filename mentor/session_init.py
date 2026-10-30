#!/usr/bin/env python3
"""Bounded, network-free Codex SessionStart loader for mentor policy and router."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ('development-discipline', 'research-supervisor', 'progress-and-recovery',
          'experiment-design', 'evidence-and-overfitting', 'evaluation-design')
CORE = ('mentor/AGENTS.md', 'mentor/ROUTING.md')
MAX_CONTEXT_BYTES = 12000


def initialize(root, event):
    root = root.resolve()
    failures, texts, hashes = [], {}, {}
    if event.get('hook_event_name') != 'SessionStart':
        failures.append('unexpected_event')
    try:
        Path(event['cwd']).resolve().relative_to(root)
    except (KeyError, ValueError, TypeError):
        failures.append('workspace_mismatch')
    for name in CORE + tuple('mentor/skills/{}/SKILL.md'.format(s) for s in SKILLS):
        path = root / name
        try:
            path.resolve().relative_to(root)
            with path.open('rb') as source:
                data = source.read(65537)
            if not data or len(data) > 65536:
                raise ValueError('source_size')
            text = data.decode('utf-8')
            if name.endswith('SKILL.md'):
                skill = path.parent.name
                if not re.search(r'^name:\s*' + re.escape(skill) + r'\s*$', text, re.M):
                    raise ValueError('skill_name')
                link = root / '.agents/skills' / skill
                if not link.is_symlink() or link.resolve() != path.parent.resolve():
                    raise ValueError('discovery_link')
            else:
                texts[name] = text
            hashes[name] = hashlib.sha256(data).hexdigest()
        except (OSError, ValueError, UnicodeError):
            failures.append(name)
    if sum(len(t.encode()) for t in texts.values()) > MAX_CONTEXT_BYTES:
        failures.append('context_size_limit')
    if failures:
        notice = 'MENTOR_INIT_FAILED: ' + ', '.join(failures)
        return {'continue': True, 'systemMessage': notice,
                'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext':
                    notice + '\nTell the user mentor initialization failed before substantive work. '
                    'Do not claim mentor or router guidance loaded successfully. Use root workspace '
                    'safety instructions, diagnose the named source, and do not silently retry or bypass it.'}}
    context = ('MENTOR_INIT_OK\nMentor policy and router loaded from canonical workspace sources. '
               'Six specialist entrypoints and discovery links verified; load full bodies selectively.\n'
               + '\n'.join('{} sha256={}'.format(name, hashes[name]) for name in CORE)
               + '\n\n' + '\n\n'.join('SOURCE: {}\n{}'.format(name, texts[name]) for name in CORE))
    return {'continue': True, 'hookSpecificOutput': {
        'hookEventName': 'SessionStart', 'additionalContext': context}}


def main():
    try:
        raw = sys.stdin.read(65537)
        event = json.loads(raw) if len(raw) <= 65536 else {}
        result = initialize(ROOT, event if isinstance(event, dict) else {})
    except Exception:
        result = {'continue': True, 'systemMessage': 'MENTOR_INIT_FAILED: invalid initialization input',
                  'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext':
                      'MENTOR_INIT_FAILED. Tell the user initialization failed; do not claim mentor/router loaded.'}}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
