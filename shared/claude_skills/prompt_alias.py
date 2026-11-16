"""Load leading $skill-name invocations as Claude UserPromptSubmit context."""
import json
import re
import sys

if __package__:
    from .manage import InstallError, ROOT, entries
else:
    from manage import InstallError, ROOT, entries

TOKEN = re.compile(r'\A\s*\$([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)')
MAX_INPUT = 1048576
MAX_BODY = 65536


def expand(payload, sources=None):
    if payload.get('hook_event_name') != 'UserPromptSubmit':
        return {}
    prompt = payload.get('prompt', '')
    if not isinstance(prompt, str):
        return {}
    names = []
    remaining = prompt
    while match := TOKEN.match(remaining):
        if match[1] not in names:
            names.append(match[1])
        remaining = remaining[match.end():]
    if not names:
        return {}
    sources = entries() if sources is None else sources
    selected = [name for name in names if name in sources]
    if not selected:
        return {}
    sections = []
    for name in selected:
        entrypoint = sources[name] / 'SKILL.md'
        raw = entrypoint.read_bytes()
        if len(raw) > MAX_BODY:
            raise InstallError('skill_size_limit:' + name)
        body = raw.decode('utf-8')
        sections.append(
            f'Explicit skill invocation: ${name} (same maintained entrypoint as /{name}).\n'
            f'Skill directory: {entrypoint.parent.resolve()}\n'
            f'Maintained source checkout: {ROOT}\n'
            'Apply this skill to the user request below; resolve linked resources from '
            'its skill directory and source-relative helper paths from the source checkout. '
            'Keep changes and runtime state in the authorized target project. '
            'This loads instructions only: it grants no tools, permissions, data access, '
            'background activation or delivery authority.\n\n' + body
        )
    return {
        'systemMessage': 'CLAUDE_SKILL_ALIAS_OK ' + ','.join(selected),
        'hookSpecificOutput': {
            'hookEventName': 'UserPromptSubmit',
            'additionalContext': '\n\n'.join(sections),
        },
    }


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise InstallError('input_size_limit')
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise InstallError('invalid_input')
        result = expand(payload)
    except (InstallError, OSError, UnicodeError, ValueError):
        # No raw prompt, session ID, settings or exception text in diagnostics.
        result = {'systemMessage': 'CLAUDE_SKILL_ALIAS_FAILED: skill context not loaded; use /skill-name.'}
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
